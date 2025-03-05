from typing import Callable

import torch
from diffusers import CogView4Transformer2DModel, FlowMatchEulerDiscreteScheduler
from diffusers.models.transformers.transformer_sd3 import SD3Transformer2DModel
from tqdm import tqdm

from invokeai.app.invocations.baseinvocation import BaseInvocation, Classification, invocation
from invokeai.app.invocations.constants import LATENT_SCALE_FACTOR
from invokeai.app.invocations.fields import (
    FieldDescriptions,
    Input,
    InputField,
    SD3ConditioningField,
    WithBoard,
    WithMetadata,
)
from invokeai.app.invocations.primitives import LatentsOutput
from invokeai.app.services.shared.invocation_context import InvocationContext
from invokeai.backend.flux.sampling_utils import clip_timestep_schedule_fractional
from invokeai.backend.model_manager.config import BaseModelType, ModelType, SubModelType
from invokeai.backend.sd3.extensions.inpaint_extension import InpaintExtension
from invokeai.backend.stable_diffusion.diffusers_pipeline import PipelineIntermediateState
from invokeai.backend.stable_diffusion.diffusion.conditioning_data import CogView4ConditioningInfo
from invokeai.backend.util.devices import TorchDevice


@invocation(
    "cogview4_denoise",
    title="CogView4 Denoise",
    tags=["image", "cogview4"],
    category="image",
    version="1.0.0",
    classification=Classification.Prototype,
)
class CogView4DenoiseInvocation(BaseInvocation, WithMetadata, WithBoard):
    """Run the denoising process with a CogView4 model."""

    positive_conditioning: SD3ConditioningField = InputField(
        description=FieldDescriptions.positive_cond, input=Input.Connection
    )
    negative_conditioning: SD3ConditioningField = InputField(
        description=FieldDescriptions.negative_cond, input=Input.Connection
    )
    cfg_scale: float | list[float] = InputField(default=3.5, description=FieldDescriptions.cfg_scale, title="CFG Scale")
    width: int = InputField(default=1024, multiple_of=16, description="Width of the generated image.")
    height: int = InputField(default=1024, multiple_of=16, description="Height of the generated image.")
    steps: int = InputField(default=10, gt=0, description=FieldDescriptions.steps)
    seed: int = InputField(default=0, description="Randomness seed for reproducibility.")

    @torch.no_grad()
    def invoke(self, context: InvocationContext) -> LatentsOutput:
        latents = self._run_diffusion(context)
        latents = latents.detach().to("cpu")

        name = context.tensors.save(tensor=latents)
        return LatentsOutput.build(latents_name=name, latents=latents, seed=None)

    def _load_text_conditioning(
        self,
        context: InvocationContext,
        conditioning_name: str,
        dtype: torch.dtype,
        device: torch.device,
    ) -> torch.Tensor:
        # Load the conditioning data.
        cond_data = context.conditioning.load(conditioning_name)
        assert len(cond_data.conditionings) == 1
        cogview4_conditioning = cond_data.conditionings[0]
        assert isinstance(cogview4_conditioning, CogView4ConditioningInfo)
        cogview4_conditioning = cogview4_conditioning.to(dtype=dtype, device=device)

        return cogview4_conditioning.glm_embeds

    def _get_noise(
        self,
        batch_size: int,
        num_channels_latents: int,
        height: int,
        width: int,
        dtype: torch.dtype,
        device: torch.device,
        seed: int,
    ) -> torch.Tensor:
        # We always generate noise on the same device and dtype then cast to ensure consistency across devices/dtypes.
        rand_device = "cpu"
        rand_dtype = torch.float16

        return torch.randn(
            batch_size,
            num_channels_latents,
            int(height) // LATENT_SCALE_FACTOR,
            int(width) // LATENT_SCALE_FACTOR,
            device=rand_device,
            dtype=rand_dtype,
            generator=torch.Generator(device=rand_device).manual_seed(seed),
        ).to(device=device, dtype=dtype)

    def _prepare_cfg_scale(self, num_timesteps: int) -> list[float]:
        """Prepare the CFG scale list.

        Args:
            num_timesteps (int): The number of timesteps in the scheduler. Could be different from num_steps depending
            on the scheduler used (e.g. higher order schedulers).

        Returns:
            list[float]: _description_
        """
        if isinstance(self.cfg_scale, float):
            cfg_scale = [self.cfg_scale] * num_timesteps
        elif isinstance(self.cfg_scale, list):
            assert len(self.cfg_scale) == num_timesteps
            cfg_scale = self.cfg_scale
        else:
            raise ValueError(f"Invalid CFG scale type: {type(self.cfg_scale)}")

        return cfg_scale

    def _init_scheduler(self) -> FlowMatchEulerDiscreteScheduler:
        # The default FlowMatchEulerDiscreteScheduler configs are copied from:
        # https://huggingface.co/THUDM/CogView4-6B/blob/fb6f57289c73ac6d139e8d81bd5a4602d1877847/scheduler/scheduler_config.json
        return FlowMatchEulerDiscreteScheduler(
            num_train_timesteps=1000,
            shift=1.0,
            use_dynamic_shifting=True,
            base_shift=0.25,
            max_shift=0.75,
            base_image_seq_len=256,
            max_image_seq_len=4096,
            invert_sigmas=False,
            shift_terminal=None,
            use_karras_sigmas=False,
            use_exponential_sigmas=False,
            use_beta_sigmas=False,
            time_shift_type="linear",
        )

    def _calculate_timestep_shift(
        self,
        image_seq_len: int,
        base_seq_len: int = 256,
        base_shift: float = 0.25,
        max_shift: float = 0.75,
    ) -> float:
        m = (image_seq_len / base_seq_len) ** 0.5
        mu = m * max_shift + base_shift
        return mu

    def _prepare_timesteps(
        self,
        scheduler: FlowMatchEulerDiscreteScheduler,
        num_steps: int,
        image_seq_len: int,
    ) -> list[int]:
        """Prepare the timestep schedule."""

        # TODO(ryand): Clean this up. It was copied from diffusers, but there's a bunch of duplicate logic here.
        timesteps = torch.linspace(scheduler.config.num_train_timesteps, 1.0, num_steps)
        timesteps = timesteps.to(torch.int64).to(torch.float32)
        sigmas = timesteps / scheduler.config.num_train_timesteps
        mu = self._calculate_timestep_shift(
            image_seq_len,
            scheduler.config.base_image_seq_len,
            scheduler.config.base_shift,
            scheduler.config.max_shift,
        )
        scheduler.set_timesteps(
            num_inference_steps=num_steps,
            device=TorchDevice.choose_torch_device(),
            sigmas=sigmas,
            mu=mu,
            timesteps=timesteps,
        )
        timesteps = scheduler.timesteps
        return timesteps.tolist()

    def _run_diffusion(
        self,
        context: InvocationContext,
    ):
        inference_dtype = TorchDevice.choose_torch_dtype()
        device = TorchDevice.choose_torch_device()

        transformer_info = context.models.load_by_attrs(
            name="CogView4",
            base=BaseModelType.StableDiffusion3,
            type=ModelType.Main,
            submodel_type=SubModelType.Transformer,
        )
        assert isinstance(transformer_info.model, CogView4Transformer2DModel)

        # Load/process the conditioning data.
        # TODO(ryand): Make CFG optional.
        do_classifier_free_guidance = True
        pos_prompt_embeds = self._load_text_conditioning(
            context=context,
            conditioning_name=self.positive_conditioning.conditioning_name,
            dtype=inference_dtype,
            device=device,
        )
        neg_prompt_embeds = self._load_text_conditioning(
            context=context,
            conditioning_name=self.negative_conditioning.conditioning_name,
            dtype=inference_dtype,
            device=device,
        )
        # TODO(ryand): Support both sequential and batched CFG inference.
        prompt_embeds = torch.cat([neg_prompt_embeds, pos_prompt_embeds], dim=0)

        # Prepare misc. conditioning variables.
        # TODO(ryand): We could expose these as params (like with SDXL). But, we should experiment to see if they are
        # useful first.
        original_size = torch.tensor([(self.height, self.width)], dtype=prompt_embeds.dtype, device=device)
        target_size = torch.tensor([(self.height, self.width)], dtype=prompt_embeds.dtype, device=device)
        crops_coords_top_left = torch.tensor([(0, 0)], dtype=prompt_embeds.dtype, device=device)

        # Prepare timesteps
        image_seq_len = ((self.height // LATENT_SCALE_FACTOR) * (self.width // LATENT_SCALE_FACTOR)) // (
            transformer_info.model.config.patch_size**2
        )
        scheduler = self._init_scheduler()
        timesteps = self._prepare_timesteps(scheduler=scheduler, num_steps=self.steps, image_seq_len=image_seq_len)

        # Resume here...

        # Prepare the timestep schedule.
        # We add an extra step to the end to account for the final timestep of 0.0.
        timesteps: list[float] = torch.linspace(1, 0, self.steps + 1).tolist()
        # Clip the timesteps schedule based on denoising_start and denoising_end.
        timesteps = clip_timestep_schedule_fractional(timesteps, self.denoising_start, self.denoising_end)
        total_steps = len(timesteps) - 1

        # Prepare the CFG scale list.
        cfg_scale = self._prepare_cfg_scale(total_steps)

        # Load the input latents, if provided.
        init_latents = context.tensors.load(self.latents.latents_name) if self.latents else None
        if init_latents is not None:
            init_latents = init_latents.to(device=device, dtype=inference_dtype)

        # Generate initial latent noise.
        num_channels_latents = transformer_info.model.config.in_channels
        assert isinstance(num_channels_latents, int)
        noise = self._get_noise(
            batch_size=1,
            num_channels_latents=num_channels_latents,
            height=self.height,
            width=self.width,
            dtype=inference_dtype,
            device=device,
            seed=self.seed,
        )

        # Prepare input latent image.
        if init_latents is not None:
            # Noise the init_latents by the appropriate amount for the first timestep.
            t_0 = timesteps[0]
            latents = t_0 * noise + (1.0 - t_0) * init_latents
        else:
            # init_latents are not provided, so we are not doing image-to-image (i.e. we are starting from pure noise).
            if self.denoising_start > 1e-5:
                raise ValueError("denoising_start should be 0 when initial latents are not provided.")
            latents = noise

        # If len(timesteps) == 1, then short-circuit. We are just noising the input latents, but not taking any
        # denoising steps.
        if len(timesteps) <= 1:
            return latents

        # Prepare inpaint extension.
        inpaint_mask = self._prep_inpaint_mask(context, latents)
        inpaint_extension: InpaintExtension | None = None
        if inpaint_mask is not None:
            assert init_latents is not None
            inpaint_extension = InpaintExtension(
                init_latents=init_latents,
                inpaint_mask=inpaint_mask,
                noise=noise,
            )

        step_callback = self._build_step_callback(context)

        step_callback(
            PipelineIntermediateState(
                step=0,
                order=1,
                total_steps=total_steps,
                timestep=int(timesteps[0]),
                latents=latents,
            ),
        )

        with transformer_info.model_on_device() as (cached_weights, transformer):
            assert isinstance(transformer, SD3Transformer2DModel)

            # 6. Denoising loop
            for step_idx, (t_curr, t_prev) in tqdm(list(enumerate(zip(timesteps[:-1], timesteps[1:], strict=True)))):
                # Expand the latents if we are doing CFG.
                latent_model_input = torch.cat([latents] * 2) if do_classifier_free_guidance else latents
                # Expand the timestep to match the latent model input.
                # Multiply by 1000 to match the default FlowMatchEulerDiscreteScheduler num_train_timesteps.
                timestep = torch.tensor([t_curr * 1000], device=device).expand(latent_model_input.shape[0])

                noise_pred = transformer(
                    hidden_states=latent_model_input,
                    timestep=timestep,
                    encoder_hidden_states=prompt_embeds,
                    pooled_projections=pooled_prompt_embeds,
                    joint_attention_kwargs=None,
                    return_dict=False,
                )[0]

                # Apply CFG.
                if do_classifier_free_guidance:
                    noise_pred_uncond, noise_pred_cond = noise_pred.chunk(2)
                    noise_pred = noise_pred_uncond + cfg_scale[step_idx] * (noise_pred_cond - noise_pred_uncond)

                # Compute the previous noisy sample x_t -> x_t-1.
                latents_dtype = latents.dtype
                latents = latents.to(dtype=torch.float32)
                latents = latents + (t_prev - t_curr) * noise_pred
                latents = latents.to(dtype=latents_dtype)

                if inpaint_extension is not None:
                    latents = inpaint_extension.merge_intermediate_latents_with_init_latents(latents, t_prev)

                step_callback(
                    PipelineIntermediateState(
                        step=step_idx + 1,
                        order=1,
                        total_steps=total_steps,
                        timestep=int(t_curr),
                        latents=latents,
                    ),
                )

        return latents

    def _build_step_callback(self, context: InvocationContext) -> Callable[[PipelineIntermediateState], None]:
        def step_callback(state: PipelineIntermediateState) -> None:
            context.util.sd_step_callback(state, BaseModelType.StableDiffusion3)

        return step_callback
