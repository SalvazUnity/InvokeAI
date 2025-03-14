import { Divider, Flex } from '@invoke-ai/ui-library';
import { useAppSelector } from 'app/store/storeHooks';
import { FocusRegionWrapper } from 'common/components/FocusRegionWrapper';
import { CanvasAddEntityButtons } from 'features/controlLayers/components/CanvasAddEntityButtons';
import { CanvasEntityList } from 'features/controlLayers/components/CanvasEntityList/CanvasEntityList';
import { EntityListSelectedEntityActionBar } from 'features/controlLayers/components/CanvasEntityList/EntityListSelectedEntityActionBar';
import { selectHasEntities } from 'features/controlLayers/store/selectors';
import { memo } from 'react';

import { ParamDenoisingStrength } from './ParamDenoisingStrength';

export const CanvasLayersPanelContent = memo(() => {
  const hasEntities = useAppSelector(selectHasEntities);

  return (
    <FocusRegionWrapper region="layers" w="full" h="full">
      <Flex flexDir="column" gap={2} w="full" h="full">
        <EntityListSelectedEntityActionBar />
        <Divider py={0} />
        <ParamDenoisingStrength />
        <Divider py={0} />
        {!hasEntities && <CanvasAddEntityButtons />}
        {hasEntities && <CanvasEntityList />}
      </Flex>
    </FocusRegionWrapper>
  );
});

CanvasLayersPanelContent.displayName = 'CanvasLayersPanelContent';
