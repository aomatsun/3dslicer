import logging
import os
from itertools import chain

import ctk
import numpy as np
import qt
import slicer
from slicer.ScriptedLoadableModule import *

from RFReconstruction import RFReconstructionLogic
from RFViewerHomeLib import RFViewerWidget, createFileSelector, translatable, showVolumeOnSlices, wrapInQTimer, \
  removeNodesFromMRMLScene
from RFVisualizationLib import RFLayoutType, ViewTag


class RFPanoramaReconstruction(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "RFPanoramaReconstruction" # TODO make this more human readable by adding spaces
    self.parent.categories = ["Examples"]
    self.parent.dependencies = []
    self.parent.contributors = [""] # replace with "Firstname Lastname (Organization)"
    self.parent.helpText = """"""
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = """""" # replace with organization, grant and thanks.

#
# RFPanoramaReconstructionWidget
#
@translatable
class RFPanoramaReconstructionWidget(RFViewerWidget):
  def __init__(self, parent):
    RFViewerWidget.__init__(self, parent)
    self._mnriLineEdit = None
    self._mnri_file_path = ""
    self._logic = RFPanoramaReconstructionLogic()
    self.projectionsVolume = None
    self.panoramaVolume = None
    self._reconstructButton = None

  def setup(self):
    RFViewerWidget.setup(self)

    # Instantiate and connect widgets ...
    self._mnriLineEdit = createFileSelector(self.updateReconstructButtonEnabled, [self.tr("MNRI File (*.mnri)")])

    parametersFormLayout = qt.QFormLayout()
    parametersFormLayout.addRow(self.tr("MNRI File"), self._mnriLineEdit)

    #
    # initial angle
    #
    self.initialAngleSliderWidget = self.createInitialAngleSlider()
    self.initialAngleSliderWidget.connect("valueChanged(double)", self.onParameterModified)
    parametersFormLayout.addRow(self.tr("Initial angle"), self.initialAngleSliderWidget)

    self.numberOfAnglesSliderWidget = self.createNumberOfAnglesSlider()
    self.numberOfAnglesSliderWidget.connect("valueChanged(double)", self.onParameterModified)
    parametersFormLayout.addRow(self.tr("Field of View"), self.numberOfAnglesSliderWidget)

    self.startXSliderWidget = self.createStartXSlider()
    self.startXSliderWidget.connect("valueChanged(double)", self.onParameterModified)
    parametersFormLayout.addRow(self.tr("Extent"), self.startXSliderWidget)

    self.layout.addLayout(parametersFormLayout)

    #
    # Apply Button
    #
    self._reconstructButton = ctk.ctkCheckablePushButton()
    self._reconstructButton.text = self.tr("Reconstruct")
    self._reconstructButton.connect("clicked(bool)", self.onStartReconstruction)
    self._reconstructButton.connect("checkBoxToggled(bool)", self.onParameterModified)
    self.layout.addWidget(self._reconstructButton)

    # Add vertical spacer
    self.layout.addStretch(1)

    # Initialize parameters and refresh reconstruction button
    self.initializeParameters()
    self.updateReconstructButtonEnabled()

  def createInitialAngleSlider(self):
    initialAngleSliderWidget = ctk.ctkSliderWidget()
    initialAngleSliderWidget.singleStep = 1.0
    initialAngleSliderWidget.minimum = -180
    initialAngleSliderWidget.maximum = 180
    initialAngleSliderWidget.setToolTip(self.tr("Offset initial angle."))
    return initialAngleSliderWidget

  def createNumberOfAnglesSlider(self):
    numberOfAnglesSlider = ctk.ctkSliderWidget()
    numberOfAnglesSlider.singleStep = 1.0
    numberOfAnglesSlider.minimum = 1
    numberOfAnglesSlider.maximum = 180
    numberOfAnglesSlider.setToolTip(self.tr("Set the angle range to consider."))
    return numberOfAnglesSlider

  def createStartXSlider(self):
    startXSlider = ctk.ctkSliderWidget()
    startXSlider.singleStep = 1.0
    startXSlider.minimum = 0
    startXSlider.maximum = 100
    startXSlider.setToolTip(self.tr("Set the number of pixels per angle to consider."))
    return startXSlider

  def initializeParameters(self):
    self.initialAngleSliderWidget.value = 0
    self.numberOfAnglesSliderWidget.value = 80
    self.startXSliderWidget.maximum = 180

    if os.path.isfile(self._mnriLineEdit.currentPath):
      mnri_settings = self._logic.MNRISettings(self._mnriLineEdit.currentPath)
      self.startXSliderWidget.maximum = int(mnri_settings.value("Frame/FrameWidth") / 2)

  def updateReconstructButtonEnabled(self):
    isEnabled = os.path.isfile(self._mnriLineEdit.currentPath)
    self._reconstructButton.setEnabled(isEnabled)

    # Save MNRI file path to history triggers line path changed. Only update button if the path has actually changed.
    if isEnabled and os.path.normpath(self._mnriLineEdit.currentPath) != os.path.normpath(self._mnri_file_path):
      self.initializeParameters()

  def onParameterModified(self):
    """ Called when checkbox is toggled """
    if self._reconstructButton.checkState == qt.Qt.Checked:
      self.onStartReconstruction()

  def onStartReconstruction(self):
    """
    Read an MNRI file,
    Called when reconstruct button is clicked, or when a parameter is modified
    if reconstruct button checkbox is checked.
    """
    # Unload current Node from the scene
    slicer.modules.RFViewerHomeWidget.getDataLoader().setCurrentVolumeNode(None)

    mnri_file_path = os.path.normpath(self._mnriLineEdit.currentPath)
    initialAngle = self.initialAngleSliderWidget.value
    numberOfAngles = self.numberOfAnglesSliderWidget.value
    startX = self.startXSliderWidget.value

    [self.panoramaVolume, self.projectionsVolume] = self._logic.run(
      mnri_file_path,
      initialAngle,
      numberOfAngles,
      startX,
      self.panoramaVolume,
      self.projectionsVolume if mnri_file_path == self._mnri_file_path else None)

    self._mnri_file_path = mnri_file_path
    self.showPanoramaView()
    self._mnriLineEdit.addCurrentPathToHistory()

  def showPanoramaView(self):
    slicer.modules.RFVisualizationWidget.setSlicerLayout(RFLayoutType.RFPanoramaLayout)
    showVolumeOnSlices(self.panoramaVolume.GetID(), ViewTag.panoramicViewTags())
    slicer.modules.RFVisualizationWidget.fitSlicesToBackground()
    slicer.modules.RFVisualizationWidget.setVolumeNode(self.panoramaVolume)
    self.panoramaVolume.GetScalarVolumeDisplayNode().AutoWindowLevelOn()
    showVolumeOnSlices("", ViewTag.mainViewTags())

  def setVolumeNode(self, volumeNode):
    removeNodesFromMRMLScene([self.panoramaVolume, self.projectionsVolume])
    self.panoramaVolume = None
    self.projectionsVolume = None


#
# RFPanoramaReconstructionLogic
#

def stitchColumns(columnList):
  return np.concatenate(columnList, axis=1)

def getColumn(array2D, x, width):
  return array2D[:, int(x + 0.5):int(x+width+0.5)]
  # return array2D[:, (x-width/2):(x+width/2)]

def get2DSlice(array, nSlice):
  return array[nSlice, :, :]

def get3DSlice(array, nSlice):
  return get2DSlice(array, nSlice)[np.newaxis]

class RFPanoramaReconstructionLogic(RFReconstructionLogic):
  """
  2D panorama reconstruction from stack of frames
  """

  def __init__(self):
    super(RFPanoramaReconstructionLogic, self).__init__()
    self._projectionName = 'PanoramaReconProjectionVol'
    self._panoramaName = self._projectionName + "-panorama"
    self._initNames = True

  @staticmethod
  def generateNodeName(baseName):
    nodeName = slicer.mrmlScene.GetUniqueNameByString(baseName)
    slicer.modules.RFViewerHomeWidget.getDataLoader().addIgnoredVolumeName(nodeName)
    return nodeName

  def run(self, mnri_file_path, initialAngleOffset=0, numberOfAngles=80, startX=0, panoramaVolume=None,
          projectionsVolume=None):
    """
    Run the actual algorithm
    """

    if self._initNames:
      self.generateNodeName(self._projectionName)
      self.generateNodeName(self._panoramaName)

    logging.info('Reconstruct Panorama')
    mnri_settings = self.MNRISettings(mnri_file_path)
    if projectionsVolume is None:
      logging.info('Load frames from MNRI')

      mhdFilePath = self.createMhdFile(mnri_file_path)
      # TODO: load volume silently
      projectionsVolume = slicer.util.loadVolume(mhdFilePath,
                                                 {'show': False, 'name': self.generateNodeName(self._projectionName)})
    inputImageData = projectionsVolume.GetImageData()

    # Get input image info
    inputSize = inputImageData.GetDimensions()
    numberOfSlices = inputSize[2]
    sliceSize = list(inputSize[0:2])
    inputOrigin = projectionsVolume.GetOrigin()
    inputSpacing = projectionsVolume.GetSpacing()
    inputImageDirections = [[0] * 3] * 3
    projectionsVolume.GetIJKToRASDirections(inputImageDirections)

    logging.info('inputSize: {}'.format(inputSize))
    logging.info('numberOfSlices: {}'.format(numberOfSlices))
    logging.info('sliceSize: {}'.format(sliceSize))
    logging.info('inputOrigin: {}'.format(inputOrigin))
    logging.info('inputSpacing: {}'.format(inputSpacing))
    logging.info('inputImageDirections: {}'.format(inputImageDirections))

    array = slicer.util.arrayFromVolume(projectionsVolume)
    totalAngle = mnri_settings.value("Geometry/TotalAngle") # 360
    offsetOrient = mnri_settings.value("Geometry/OffsetOrient") # -0.3
    firstSliceAngle = mnri_settings.value("Geometry/InitAngle")

    logging.info('totalAngle: {}'.format(totalAngle))
    logging.info('offsetOrient: {}'.format(offsetOrient))

    def relativeAngleToSliceIndex(angle):
      # Convert an angle to a slice index where 0 is frontAngle
      projectionAngle = 90 + firstSliceAngle + angle + initialAngleOffset
      return int(projectionAngle * (numberOfSlices / totalAngle))
      # return int((angle + initialAngle - offsetOrient) * (numberOfSlices / totalAngle))

    # angles = [-160, -130, -100, -70, -40, 0, 40, 70, 100, 130, 160]
    # angles = range(-180, 160, 3)
    # indices = [sliceIndexForAngleFromInitialAngle(angle) for angle in angles]

    reverse = -90 < initialAngleOffset < 90
    firstSlice = relativeAngleToSliceIndex(-numberOfAngles) % numberOfSlices
    lastSlice = relativeAngleToSliceIndex(numberOfAngles) % numberOfSlices
    print(firstSlice, lastSlice, reverse)

    slices = []
    if firstSlice < lastSlice:
      slices = range(firstSlice, lastSlice)
    else:
      slices = chain(range(firstSlice, numberOfSlices), range(0, lastSlice))

    slices = list(slices)
    if reverse:
      slices.reverse()
    print(slices)

    columns = []

    # sliceWidth = sliceSize[0]
    frameWidth = mnri_settings.value("Frame/FrameWidth")
    # columnWidth = int(frameWidth / len(slices))
    # N slices are covering frameWidth - (2*startX) pixels
    columnWidth = (frameWidth - 2*startX) / len(slices)
    # middle of middle slice shoul
    # For slice 0, column should start at startX
    # For middle slice, column should be start frameWidth/2-columnWidth/2
    # For slice n-1, column should start at frameWidth-columnWidth-startX
    # inc = (frameWidth-columnWidth)/ ((len(slices) - 1))
    inc = (frameWidth-columnWidth-startX) / (len(slices) - 1)
    i = 0
    for index in slices:
      slice = get2DSlice(array, index)
      column = getColumn(slice, i * inc + startX, columnWidth)
      columns.append(column)
      i += 1

    # columns.reverse()
    stiched = stitchColumns(columns)
    stiched3D = stiched[np.newaxis]

    volumesLogic = slicer.modules.volumes.logic()
    if panoramaVolume is None:
      panoramaVolume = volumesLogic.CloneVolumeWithoutImageData(
        slicer.mrmlScene, projectionsVolume, self.generateNodeName(self._panoramaName))
      panoramaVolume.SetOrigin(inputOrigin)
      panoramaVolume.SetSpacing(inputSpacing)
      coronal_direction = [[-1, 0, 0], [0, 0, 1], [0, -1, 0]]
      panoramaVolume.SetIJKToRASDirections(coronal_direction)
      panoramaVolume.CreateDefaultDisplayNodes()
      panoramaVolume.CreateDefaultStorageNode()

    stiched3D = self.scaleFromRawToAttenuation(stiched3D, mnri_settings)
    stiched3D = self.scaleFromAttenuationToHounsfieldUnits(stiched3D, mnri_settings)
    slicer.util.updateVolumeFromArray(panoramaVolume, stiched3D)

    logging.info('Processing completed')

    return [panoramaVolume, projectionsVolume]

  @staticmethod
  def scaleFromAttenuationToHounsfieldUnits(att_arr, mnri_settings):
    """
    Convert input array from raw values to Hounsfield Units
    """
    # Extract air and water normalized values from presets
    CTValuePreset = qt.QSettings('CTValuePreset.ini', qt.QSettings.IniFormat)  # File must be next to RFViewer.ini
    selected_preset = int(mnri_settings.value('Volume/TFPresetIndex'))
    air_norm_value = float(CTValuePreset.value('CTValuePreset{:04d}_Air'.format(selected_preset), 0))
    water_norm_value = float(CTValuePreset.value('CTValuePreset{:04d}_Water'.format(selected_preset), 0.018))

    # Normalize array and scale the array
    shift = -water_norm_value
    scale = 1000. / (water_norm_value - air_norm_value)

    return (att_arr + shift) * scale

  @staticmethod
  def scaleFromRawToAttenuation(array, mnri_settings):
    # Frame is normalized between [0, 2^NBB]
    iDark, i0 = RFReconstructionLogic.range(mnri_settings)
    #att_arr = -np.log(max( (array- iDark) / (i0 - iDark), 1))
    att_arr = array
    att_arr[att_arr <= 0] = 1
    return -np.log((att_arr - iDark) / (i0 - iDark))
