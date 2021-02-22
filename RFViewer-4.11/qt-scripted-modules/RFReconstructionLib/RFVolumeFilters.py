# Import can fail if CUDA is not available on the computer
try:
  from enum import unique, Enum
  import slicer

  from SimpleFilters import SimpleFiltersLogic
  import SimpleITK as sitk
except Exception as e:
  raise ImportError(str(e))


class VolumeFiltersLogic:
  @unique
  class Type(Enum):
    Median = 0
    Gaussian = 1
    Sharpen = 2

  def __init__(self):
    slicer.util.getModuleGui(slicer.modules.simplefilters)

    self._logic = SimpleFiltersLogic()

  def run(self, filter, volumeNode):
    return self._logic.run(filter, volumeNode, None, volumeNode)

  def applyMedianFilter(self, volumeNode, kernelSize):
    
    filter = sitk.MedianImageFilter()
    filter.SetRadius(int(kernelSize))

    self.run(filter, volumeNode)

  def applyGaussianFilter(self, volumeNode, stddev):
    filter = sitk.DiscreteGaussianImageFilter()
    filter.SetVariance(stddev)

    self.run(filter, volumeNode)

  def applySharpenFilter(self, volumeNode):
    filter = sitk.LaplacianSharpeningImageFilter()

    self.run(filter, volumeNode)
