import type {
  CanvasControlLayerState,
  CanvasInpaintMaskState,
  CanvasRasterLayerState,
  CanvasReferenceImageState,
  CanvasRegionalGuidanceState,
} from 'features/controlLayers/store/types';
import type { ParameterModel } from 'features/parameters/types/parameterSchemas';
import type { TFunction } from 'i18next';

export const getRegionalGuidanceWarnings = (
  entity: CanvasRegionalGuidanceState,
  model: ParameterModel | null,
  t: TFunction
): string[] => {
  const warnings: string[] = [];

  if (entity.objects.length === 0) {
    // Layer is in empty state - skip other checks
    warnings.push(t('parameters.invoke.layer.emptyLayer'));
  } else {
    if (entity.positivePrompt === null && entity.negativePrompt === null && entity.referenceImages.length === 0) {
      // Must have at least 1 prompt or IP Adapter
      warnings.push(t('parameters.invoke.layer.rgNoPromptsOrIPAdapters'));
    }

    if (model) {
      if (model.base === 'sd-3' || model.base === 'sd-2') {
        // Unsupported model architecture
        warnings.push(t('controlLayers.invalidBaseModelType'));
      } else if (model.base === 'flux') {
        // Some features are not supported for flux models
        if (entity.negativePrompt !== null) {
          warnings.push(t('parameters.invoke.layer.rgNegativePromptNotSupported'));
        }
        if (entity.referenceImages.length > 0) {
          warnings.push(t('parameters.invoke.layer.rgReferenceImagesNotSupported'));
        }
        if (entity.autoNegative) {
          warnings.push(t('parameters.invoke.layer.rgAutoNegativeNotSupported'));
        }
      } else {
        entity.referenceImages.forEach(({ ipAdapter }) => {
          if (!ipAdapter.model) {
            // No model selected
            warnings.push(t('parameters.invoke.layer.ipAdapterNoModelSelected'));
          } else if (ipAdapter.model.base !== model.base) {
            // Supported model architecture but doesn't match
            warnings.push(t('parameters.invoke.layer.ipAdapterIncompatibleBaseModel'));
          }

          if (!ipAdapter.image) {
            // No image selected
            warnings.push(t('parameters.invoke.layer.ipAdapterNoImageSelected'));
          }
        });
      }
    }
  }

  return warnings;
};

export const getGlobalReferenceImageWarnings = (
  entity: CanvasReferenceImageState,
  model: ParameterModel | null,
  t: TFunction
): string[] => {
  const warnings: string[] = [];

  if (!entity.ipAdapter.model) {
    // No model selected
    warnings.push(t('parameters.invoke.layer.ipAdapterNoModelSelected'));
  } else if (model) {
    if (model.base === 'sd-3' || model.base === 'sd-2') {
      // Unsupported model architecture
      warnings.push(t('controlLayers.invalidBaseModelType'));
    } else if (entity.ipAdapter.model.base !== model.base) {
      // Supported model architecture but doesn't match
      warnings.push(t('parameters.invoke.layer.ipAdapterIncompatibleBaseModel'));
    }
  }

  if (!entity.ipAdapter.image) {
    // No image selected
    warnings.push(t('parameters.invoke.layer.ipAdapterNoImageSelected'));
  }

  return warnings;
};

export const getControlLayerWarnings = (
  entity: CanvasControlLayerState,
  model: ParameterModel | null,
  t: TFunction
): string[] => {
  const warnings: string[] = [];

  if (entity.objects.length === 0) {
    // Layer is in empty state - skip other checks
    warnings.push(t('parameters.invoke.layer.emptyLayer'));
  } else {
    if (!entity.controlAdapter.model) {
      // No model selected
      warnings.push(t('parameters.invoke.layer.controlAdapterNoModelSelected'));
    } else if (model) {
      if (model.base === 'sd-3' || model.base === 'sd-2') {
        // Unsupported model architecture
        warnings.push(t('controlLayers.invalidBaseModelType'));
      } else if (entity.controlAdapter.model.base !== model.base) {
        // Supported model architecture but doesn't match
        warnings.push(t('parameters.invoke.layer.controlAdapterIncompatibleBaseModel'));
      }
    }
  }

  return warnings;
};

export const getRasterLayerWarnings = (
  entity: CanvasRasterLayerState,
  _model: ParameterModel | null,
  t: TFunction
): string[] => {
  const warnings: string[] = [];

  if (entity.objects.length === 0) {
    // Layer is in empty state - skip other checks
    warnings.push(t('parameters.invoke.layer.emptyLayer'));
  }

  return warnings;
};

export const getInpaintMaskWarnings = (
  entity: CanvasInpaintMaskState,
  _model: ParameterModel | null,
  t: TFunction
): string[] => {
  const warnings: string[] = [];

  if (entity.objects.length === 0) {
    // Layer is in empty state - skip other checks
    warnings.push(t('parameters.invoke.layer.emptyLayer'));
  }

  return warnings;
};
