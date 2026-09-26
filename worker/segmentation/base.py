from abc import ABC, abstractmethod


class DishSegmenter(ABC):
    semantics = "dish_object = food + plate; exclude table"

    @abstractmethod
    def segment_video(self, paths, output, config, prompt=None):
        """Return one mask record per input position; never mutate input images."""

    @abstractmethod
    def segment_frame(self, rgb, config):
        """Return initialization mask candidates, not independently segmented video."""
