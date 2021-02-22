import qt
import slicer
from slicer.ScriptedLoadableModule import *
import vtk
from RFReconstruction import RFReconstructionLogic
import RFViewerHomeLib
from RFViewerHomeLib import wrapInQTimer, translatable, RFViewerWidget, showVolumeOnSlices,showVolumeOnSlice, warningMessageBox, \
  getViewBySingletonTag,ExportDirectorySettings 
from RFVisualizationLib import RFLayoutType, layoutSetup, layoutBackgroundSetup, RFVisualizationUI, IndustryType, \
  closestPowerOfTen, getAll3DViewNodes, createDiscretizableColorTransferFunctionFromColorPreset, \
  createColorNodeFromVolumePropertyNode, ViewTag
import threading
from skimage.transform import iradon, radon
import skimage
from datetime import datetime
import numpy as np
import pydicom
import os
from pydicom.pixel_data_handlers.util import apply_voi_lut
from numba import jit, cuda ,njit,float64, int32
import numba  
class RFVisualization(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "RF Visualization" # TODO make this more human readable by adding spaces
    self.parent.categories = ["RFCo"]
    self.parent.dependencies = []
    self.parent.contributors = [] # replace with "Firstname Lastname (Organization)"
    self.parent.helpText = ""
    self.parent.acknowledgementText = ""


@translatable
class RFVisualizationWidget(RFViewerWidget):
  def __init__(self, parent):
    RFViewerWidget.__init__(self, parent)
    self.volumeNode = None

    self._layoutManager = None
    self._vrLogic = None

    self._currentPreset3D = None
    self._currentPreset2D = None
    self._synchronizeViews = False
    self._currentVRMode = slicer.vtkMRMLViewNode().Composite
    self._currentColor = None # Means that the color is the current preset3D color
    self._map3DColorToColorTableNode = {}

    self._previousThresholdPreset = 0.0
    self._isLoadingState = False

    self._displayNodeVisibility = {}
    self._roisVisibility = {}
    self._viewVisibility = {}

  def getVolumeDisplayNode3D(self):
    return self._vrLogic.GetFirstVolumeRenderingDisplayNode(self.volumeNode)
  def setVolumeNode(self, volumeNode):
    self.volumeNode = volumeNode


    if self.volumeNode and not self.getVolumeDisplayNode3D():
      self._vrLogic.CreateDefaultVolumeRenderingNodes(self.volumeNode)
    
    # print(volumeNode)
    self.ui.setVolumeNode(volumeNode=volumeNode, displayNode3D=self.getVolumeDisplayNode3D(),
                          isLoadingState=self._isLoadingState)

    # If volume node was cleared, presets should not be set
    if not self.volumeNode:
      return

    self.setPreset3D(self._currentPreset3D)
    self.setPreset2D(self._currentPreset2D)
    self.setVRMode(self._currentVRMode)
    self.setColorTo3D(self._currentColor)

    if self._isLoadingState:
      return

    self.fit3DViewsToVolume()
    if self.industry == IndustryType.Dental:
      self.rotateAxialViewInDentalConvention()
    self.counts = 0
    # showVolumeOnSlices(self.volumeNode.GetID(), ViewTag.mainViewTags())
    array1 = slicer.util.array(self.volumeNode.GetID())
    self.tmpArray = array1
    # try:
    mnrifilePath = os.path.join(ExportDirectorySettings.load(), "NAOMICT_UTF8.mnri")
    mnri_settings = RFReconstructionLogic.MNRISettings(mnrifilePath)
    mar_value = mnri_settings.value("Frame/Mar")
    if mar_value != 1:
      showVolumeOnSlices(self.volumeNode.GetID(), ViewTag.mainViewTags())
      return
    else:
      showVolumeOnSlices(self.volumeNode.GetID(), ViewTag.mainViewTags1())
      self.marthreshold = mnri_settings.value("Frame/MarThreshold") 
      self.marbrightthreshold = mnri_settings.value("Frame/MarBrightThreshold") 
      
    filename =  ExportDirectorySettings.load() + "/DICOM16/" + 'IMG0001.dcm'
    if os.path.exists(filename) != False:
      self.ds = pydicom.dcmread(filename)
    else:
      return
    tmp_center = self.ds.WindowCenter
    tmp_width = self.ds.WindowWidth
    self.ds.WindowCenter = tmp_width
    self.ds.WindowWidth = tmp_center
    threads = []
    index1 = 0
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)
    self.threadcount = 0
    for x in array1:
      max = np.max(x)
      if max > 30000:
        self.threadcount = self.threadcount + 1
        print(index1)
        shapes = x.shape
        t = threading.Thread(target=self.calc_mar1 , args=(shapes, x, index1,))
        threads.append(t)
        t.start()
      index1 = index1 + 1
      if self.threadcount > 15:
        print("All threads are started")
        for t1 in threads:
          t1.join() # Wait until thread terminates its task
        print("All threads completed")
        self.threadcount = 0
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)
    # showVolumeOnSlice(self.tmpArray, ViewTag.Axial)
    # self.volumeNode.GnoetImageData().SetScalars(self.tmpArray)
    showVolumeOnSlices(self.tmpArray, ViewTag.mainViewTags())
    # # except:
    # #   showVolumeOnSlices(self.tmpArray, ViewTag.mainViewTags())
  

  # @jit(fastmath=True,nopython=True)
  # def SLFilter( N, d):
  #   filterSL = np.zeros(N)
  #   for i in range(N):
  #       filterSL[i] = - 2.0 / (np.pi**2.0 * d**2.0 * (4.0 * (i - N / 2)**2.0 - 1.0))
  #   return filterSL

  # @jit( nopython=True,parallel=True, fastmath=True, cache=True)
  # def RLIRadonTransform( steps, pictureSize, projectionValue, delta):
  #   res = np.zeros((pictureSize, pictureSize))
  #   filter = self.SLFilter(pictureSize, 1)
  #   for step in range(steps):
  #       pm = projectionValue[:, step]
  #       filterPmWithoutCut = np.convolve(filter, pm)#, "same")
  #       #numba仅支持convolve前两个参数，这也就意味着无法将mode设置为"same"，
  #       #所以我们需要对卷积的结果进行一个裁剪
  #       lenFirst = len(filter)
  #       lenSecond = len(pm)
  #       lenCore = max(lenFirst, lenSecond)
  #       lenRes = len(filterPmWithoutCut)
  #       sideLen = np.int64((lenRes - lenCore) / 2.0)
  #       firstIndex = np.int64(sideLen)
  #       lastIndex = np.int64(lenRes - 1 - sideLen)
  #       #print(sideLen, firstIndex, lastIndex)
  #       filterPm = filterPmWithoutCut[firstIndex:lastIndex+1]

  #       deg = (step - 1) * delta
  #       bias = (pictureSize / 2.0) * (1 - np.cos(deg) - np.sin(deg))
  #       for row in range(pictureSize):
  #           for col in range(pictureSize):
  #               pos = bias + (col - 1) * np.cos(deg) + (row - 1) * np.sin(deg)
  #               n = np.int64(np.floor(pos))
  #               t = pos - n
  #               n = np.int64(max(0, n))
  #               n = np.int64(min(n, pictureSize - 2))
  #               p = (1 - t) * filterPm[n] + t * filterPm[n+1]
  #               res[np.int64(pictureSize - 1 - row), np.int64(col)] = res[np.int64(pictureSize - 1 - row), np.int64(col)] + p
  #   return res
 
  def calc_mar1(self, shapes, image1, index1):
    
    image = apply_voi_lut(image1, self.ds)
    print(image)
    tmp_image = image
    m = max(abs(np.min(image)),np.max(image))
    image = image + m
    omax = np.max(image)
    image = image / omax

    theta = np.linspace(0., 180., shapes[0], endpoint=False)
    sinogram = skimage.transform.radon(image, theta=theta, circle=True)
    # print("Sinogram:===>")
    # print(np.max(sinogram))
    if self.marthreshold > 0 :
      eff = self.marthreshold
    else:
      eff = 0.65
    th = np.max(sinogram) * eff
    sinogram[sinogram > th] =  th
    reconstruction_fbp = skimage.transform.iradon(sinogram, theta=theta, circle=True)
    # delta = np.pi / shapes[0]
    # reconstruction_fbp = RLIRadonTransform(shapes[0], shapes[0] + 1, sinogram, delta)
    tmp_image[tmp_image < tmp_image * 0.99 ] = 0
    # print(window_width)
    scaled_img = self.ds.WindowWidth * reconstruction_fbp - self.ds.WindowCenter 
    print("tmp_image")
    print(np.max(tmp_image))
    print(np.max(scaled_img))
    scaled_img = scaled_img + (tmp_image / (np.max(tmp_image))) * self.ds.WindowWidth
    self.tmpArray[index1] = scaled_img 
    # print(self.tmpArray[index1])
    return


  def calc_mar(self, shapes, image1, index1):
   
    image = pydicom.pixel_data_handlers.util.apply_voi_lut(image1, self.ds)
    tmpimage = self.calc_matrix(image)

    # theta = np.linspace(0., 180., 773, endpoint=False)
    sinogram = DiscreteRadonTransform(tmpimage, len(tmpimage[0]))
    # print("Sinogram:===>")
    # print(np.max(sinogram))
    if self.marthreshold > 0 :
      eff = self.marthreshold
    else:
      eff = 0.65
    th = np.max(sinogram) * eff
    sinogram[sinogram > th] =  th
    reconstruction_fbp = IRandonTransform(sinogram, len(sinogram[0]))
    tmp_image[tmp_image < tmp_image * 0.99 ] = 0
    # print(window_width)
    scaled_img = self.ds.WindowWidth * reconstruction_fbp - self.ds.WindowCenter 
    
    scaled_img = scaled_img + (tmp_image / (np.max(tmp_image))) * self.ds.WindowWidth
    self.tmpArray[index1] = scaled_img 
    # print(self.tmpArray[index1])
    return
  @staticmethod
  def rotateAxialViewInDentalConvention():
    axialView = getViewBySingletonTag(ViewTag.Axial)
    axialDentalRotationMatrix = [[-1, 0, 0], [0, -1, 0], [0, 0, -1]]
    axialRASMatrix = axialView.GetSliceToRAS()

    for i, row in enumerate(axialDentalRotationMatrix):
      for j, val in enumerate(row):
        axialRASMatrix.SetElement(i, j, val)

    axialView.UpdateMatrices()

  @wrapInQTimer
  def fit3DViewsToVolume(self):
    # Fit 3D views to new volume
    slicer.util.resetThreeDViews()

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    #
    # Initialize attributes
    #
    try:
      self.industry = IndustryType[qt.QSettings().value("IndustryType")]
    except KeyError:
      self.industry = IndustryType.Medical
    self._layoutManager = slicer.app.layoutManager()
    self._vrLogic = slicer.modules.volumerendering.logic()

    # Apply default 3D Preset
    self._currentPreset3D = self._defaultIndustry3DPreset()
    self.setPreset3D(self._currentPreset3D)

    #
    # Setup Layouts
    #
    layoutSetup(self._layoutManager)
    layoutBackgroundSetup(self._layoutManager.threeDWidget(0).mrmlViewNode())
    self.ui = RFVisualizationUI(self._vrLogic, self._currentPreset3D, self.industry)
    self.layout.addWidget(self.ui)
    self.setSlicerLayout(RFLayoutType.RFDefaultLayout)

    # Apply default 2D preset
    self._currentPreset2D = self._defaultIndustry2DPreset()
    self.setPreset2D(self._currentPreset2D)

    #
    # Connections
    #
    self.ui.layoutSelector.connect("currentIndexChanged(int)", self.onLayoutSelect)
    self.ui.preset3DSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onPreset3DSelect)
    self.ui.preset2DSelector.connect("currentIndexChanged(int)", self.onPreset2DSelect)
    self.ui.vrModeSelector.connect("currentIndexChanged(int)", self.onVRModeSelect)
    self.ui.colorSelector.connect("currentIndexChanged(int)", self.onColorSelect)
    self.ui.shiftSlider.connect("valueChanged(double)", self.onShiftSliderChanged)
    self.ui.synchronizeCheckbox.connect("stateChanged(int)", self.onSynchronizeChanged)
    self.ui.displayResliceCursorCheckbox.connect("stateChanged(int)", self.onResliceCursorDisplayed)
    self.ui.slabThicknessSlider.connect("valueChanged(int)", self.onSlabThicknessSliderChanged)
    self.ui.thicknessSelector.connect("currentIndexChanged(int)", self.onMIPThicknessChanged)

    # Add vertical spacer
    self.layout.addStretch(1)

  def _defaultIndustry3DPreset(self):
    """Get the default industry 3D rendering preset"""
    if self.industry == IndustryType.Medical:
      return self._vrLogic.GetPresetByName('プリセット1')
    return self._vrLogic.GetPresetByName('プリセット1')

  def _defaultIndustry2DPreset(self):
    """Get default 2D preset as configured in the UI without changing the current applied preset"""
    currentPreset = self.ui.preset2DSelector.currentText
    self.ui.preset2DSelector.setCurrentIndex(0)
    defaultPreset = self.ui.preset2DSelector.currentText
    self.ui.preset2DSelector.setCurrentText(currentPreset)
    return defaultPreset

  def setSlicerLayout(self, layoutType):
    self.ui.layoutSelector.setCurrentIndex(self.ui.layoutSelector.findData(layoutType))

  @wrapInQTimer
  def fitSlicesToBackground(self):
    for viewName in self._layoutManager.sliceViewNames():
      self._layoutManager.sliceWidget(viewName).fitSliceToBackground()

  def onLayoutSelect(self):
    if self._isLoadingState:
      return

    newLayout = self.ui.layoutSelector.currentData
    # Setup the layout before trying to get the viewNode, else, they won't exist
    layoutType = self.ui.layoutSelector.currentData
    
    if layoutType > RFLayoutType.RFPanoramaLayout:
      layoutType = RFLayoutType.RFMainAxialLayout
    
    self._layoutManager.setLayout(layoutType)
    if newLayout == RFLayoutType.RFTriple3D or newLayout == RFLayoutType.RFDual3D:
      self.setVRMode(self._currentVRMode)
      views = getAll3DViewNodes()
      for view in views:
        self.getVolumeDisplayNode3D().AddViewNodeID(view.GetID())
        layoutBackgroundSetup(view)

    # Apply slab thickness on new slice views
    self.onSlabThicknessSliderChanged()
    
    lm = slicer.app.layoutManager()
    if newLayout == RFLayoutType.RF2X2Layout:
      lm.sliceWidget("Red").sliceController().setLightbox(2, 2)
    if newLayout == RFLayoutType.RF3X3Layout:
      lm.sliceWidget("Red").sliceController().setLightbox(3, 3)
    if newLayout == RFLayoutType.RF4X4Layout:
      lm.sliceWidget("Red").sliceController().setLightbox(4, 4)
    if newLayout == RFLayoutType.RF5X5Layout:
      lm.sliceWidget("Red").sliceController().setLightbox(5, 5)
    # if newLayout == RFLayoutType.RF6X6Layout:
    #   lm.sliceWidget("Red").sliceController().setLightbox(6, 6)
    # if newLayout == RFLayoutType.RF7X7Layout:
    #   lm.sliceWidget("Red").sliceController().setLightbox(7, 7)
    # if newLayout == RFLayoutType.RF8X8Layout:
    #   lm.sliceWidget("Red").sliceController().setLightbox(8, 8)

  def onPreset3DSelect(self):
    if self._isLoadingState:
      return

    self._currentPreset3D = self.ui.preset3DSelector.currentNode()
    self.setPreset3D(self._currentPreset3D)

  def onPreset2DSelect(self):
    if self._isLoadingState:
      return

    self._currentPreset2D = self.ui.preset2DSelector.currentText
    self.setPreset2D(self._currentPreset2D)

  def onVRModeSelect(self):
    if self._isLoadingState:
      return

    self._currentVRMode = self.ui.vrModeSelector.currentData
    self.setVRMode(self._currentVRMode)

  def onColorSelect(self):
    if self._isLoadingState:
      return

    self._currentColor = self.ui.colorSelector.currentData
    self.setColorTo3D(self._currentColor)

  def onShiftSliderChanged(self):
    if self._isLoadingState:
      return

    if self._currentPreset3D is None:
      return

    newPosition = self.ui.shiftSlider.value
    self.ui.scalarMappingWidget.moveAllPoints(newPosition - self._previousThresholdPreset, 0., False)
    self._previousThresholdPreset = newPosition

  def setMIPThickness2Button(self):
    thickness = 2
    self.thicknessText.setText("2 mm")
    sliceNodes = slicer.util.getNodesByClass('vtkMRMLSliceNode')
    for slice in sliceNodes:
      slice.SetMipThickness(thickness)

  def onSlabThicknessSliderChanged(self):
    if self._isLoadingState:
      return
    volxstr = qt.QSettings().value("volx")
    if volxstr is None:
      volx = 100
    else:
      volx = int(qt.QSettings().value("volx"))
    if volx > 0:
      self.ui.slabThicknessSlider.setMaximum(volx)
    thickness = self.ui.slabThicknessSlider.value
    self.ui.thicknessText.setText(str(thickness) + " mm")
    sliceNodes = slicer.util.getNodesByClass('vtkMRMLSliceNode')
    for slice in sliceNodes:
      slice.SetSlabMode(vtk.VTK_IMAGE_SLAB_MAX)
      slice.SetSlabNumberOfSlices(thickness)
      slice.SetMipThickness(thickness)

  def onSynchronizeChanged(self):
    if self._isLoadingState:
      return

    self._synchronizeViews = self.ui.synchronizeCheckbox.checked
    self.ui.preset2DSelector.enabled = not self._synchronizeViews
    if not self.volumeNode:
      return

    if self._synchronizeViews and self.volumeNode.GetScalarVolumeDisplayNode():
      self.volumeNode.GetScalarVolumeDisplayNode().AutoWindowLevelOn()
      self.setColorTo2D(self._currentColor)
    else:
      self.setPreset2D(self._currentPreset2D)

  def onMIPThicknessChanged(self):
    if self._isLoadingState:
      return
    
    thickness = self.ui.thicknessSelector.currentData
    self.ui.thicknessText.setText(str(thickness) + " mm")
    sliceNodes = slicer.util.getNodesByClass('vtkMRMLSliceNode')
    for slice in sliceNodes:
      slice.SetMipThickness(thickness)

  def onResliceCursorDisplayed(self):
    if self._isLoadingState:
      return

    self._displayResliceCursor = self.ui.displayResliceCursorCheckbox.checked

    # Set 2D views
    views = slicer.util.getNodesByClass('vtkMRMLSliceCompositeNode')
    for view in views:
      view.SetSliceIntersectionVisibility(self._displayResliceCursor)

    # Set 3D view
    sliceNodes = slicer.util.getNodesByClass('vtkMRMLSliceNode')
    for slice in sliceNodes:
      slice.SetWidgetVisible(self._displayResliceCursor)

  def setPreset3D(self, preset):
    if self._isLoadingState:
      self._currentPreset3D = preset
      self.resetOffsetSlider()
      return

    displayNode3D = self.getVolumeDisplayNode3D()
    if displayNode3D is None:
      return

    displayNode3D.SetVisibility(True)
    displayNode3D.GetVolumePropertyNode().Copy(preset)
    self.resetOffsetSlider()
    self.ui.colorSelector.setCurrentIndex(0)
    if self._synchronizeViews:
      self.setColorTo2D(self._currentColor)

  def setPreset2D(self, presetName):
    """
    Set the correct 2D preset according to the preset name
    cf qSlicerScalarVolumeDisplayWidget::setPreset
    """
    if self._isLoadingState:
      self._currentPreset2D = presetName
      return

    if self.volumeNode is None:
      return

    displayNode = self.volumeNode.GetScalarVolumeDisplayNode()
    if not displayNode:
      return

    colorNodeID = ""
    window = -1
    level = 0
    if presetName == "CT-Bone":
      colorNodeID = "vtkMRMLColorTableNodeGrey"
      window = 1000
      level = 400
    elif presetName == "CT-Air":
      colorNodeID = "vtkMRMLColorTableNodeGrey"
      window = 1000
      level = -426
    elif presetName == "PET":
      colorNodeID = "vtkMRMLColorTableNodeRainbow"
      window = 10000
      level = 6000
    elif presetName == "CT-Abdomen":
      colorNodeID = "vtkMRMLColorTableNodeGrey"
      window = 350
      level = 40
    elif presetName == "CT-Brain":
      colorNodeID = "vtkMRMLColorTableNodeGrey"
      window = 100
      level = 50
    elif presetName == "CT-Lung":
      colorNodeID = "vtkMRMLColorTableNodeGrey"
      window = 1400
      level = 0.5
    elif presetName == "DTI":
      colorNodeID = "vtkMRMLColorTableNodeRainbow"
      window = 1
      level = 0.5

    if colorNodeID != "":
      displayNode.SetAndObserveColorNodeID(colorNodeID)

    if window != -1 or level != 0:
      displayNode.AutoWindowLevelOff()

    # cf qMRMLWindowLevelWidget
    if window != -1 and level != 0:
      displayNode.SetWindowLevel(window, level)
    elif window != -1:
      displayNode.SetWindow(window)
    elif level != 0:
      displayNode.SetLevel(level)
    self.ui.windowLevelWidget.pushButton1.click()
  def setVRMode(self, VRMode):
    if self._isLoadingState:
      self._currentVRMode = VRMode
      return

    views = getAll3DViewNodes()
    for view in views:
      view.SetRaycastTechnique(VRMode)

  def setColorTo3D(self, colorPreset):
    displayNode3D = self.getVolumeDisplayNode3D()
    if displayNode3D is None:
      return

    if self._isLoadingState:
      self._currentColor = colorPreset
      self.ui.scalarMappingWidget.setMRMLVolumePropertyNode(displayNode3D.GetVolumePropertyNode())
      return

    if colorPreset is None:
      self.setPreset3D(self._currentPreset3D)
    else:
      rangeCT = [0] * 2
      displayNode3D.GetVolumePropertyNode().GetColor().GetRange(rangeCT)
      colorTransferFunction = createDiscretizableColorTransferFunctionFromColorPreset(colorPreset, rangeCT)

      # only update color in order to keep the opacity
      displayNode3D.GetVolumePropertyNode().SetColor(colorTransferFunction)
      self.ui.scalarMappingWidget.setMRMLVolumePropertyNode(displayNode3D.GetVolumePropertyNode())

    if self._synchronizeViews:
      self.setColorTo2D(self._currentColor)

  def setColorTo2D(self, color):
    if self._isLoadingState:
      return

    if color is None:
      preset3DName = self._currentPreset3D.GetName()
      displayNode3D = self.getVolumeDisplayNode3D()
      if preset3DName not in self._map3DColorToColorTableNode and displayNode3D is not None:
        self._map3DColorToColorTableNode[preset3DName] = createColorNodeFromVolumePropertyNode(displayNode3D.GetVolumePropertyNode())
      currentColorID = self._map3DColorToColorTableNode[preset3DName].GetID()
    else:
      currentColorID = slicer.modules.colors.logic().GetColorTableNodeID(color)

    if self.volumeNode.GetScalarVolumeDisplayNode():
      self.volumeNode.GetScalarVolumeDisplayNode().SetAndObserveColorNodeID(currentColorID)

  def resetOffsetSlider(self):
    """
    cf qSlicerVolumeRenderingPresetComboBox::updatePresetSliderRange()
    """
    self._previousThresholdPreset = 0.0
    self.ui.shiftSlider.value = 0.0

    volumePropertyNode = self.getVolumeDisplayNode3D().GetVolumePropertyNode()
    volumePropertyNode.CalculateEffectiveRange()
    effectiveRange = volumePropertyNode.GetEffectiveRange()
    transferFunctionWidth = effectiveRange[1] - effectiveRange[0]

    self.ui.shiftSlider.minimum = -transferFunctionWidth * 2
    self.ui.shiftSlider.maximum = transferFunctionWidth * 2
    self.ui.shiftSlider.singleStep = closestPowerOfTen(transferFunctionWidth) / 500.0
    self.ui.shiftSlider.pageStep = self.ui.shiftSlider.singleStep

  def onSessionAboutToBeSaved(self):
    """Override from RFViewerWidget"""
    parameter = self.getParameterNode()
    parameter.SetParameter("VolumeNodeID", self.volumeNode.GetID())
    self.saveState()

  def saveState(self):
    """Override from RFViewerWidget"""
    parameter = self.getParameterNode()
    parameter.SetParameter("CurrentPreset2D", self._currentPreset2D)
    parameter.SetParameter("CurrentPreset3D", self._currentPreset3D.GetName())
    parameter.SetParameter("CurrentVRMode", str(self._currentVRMode))
    parameter.SetParameter("CurrentColor", str(self._currentColor))
    parameter.SetParameter("CurrentLayout", str(self.ui.layoutSelector.currentIndex))
    parameter.SetParameter("CurrentThreshold", str(self._previousThresholdPreset))
    parameter.SetParameter("IndustryType", str(self.industry.value))

  def onSessionLoaded(self):
    """Override from RFViewerWidget"""
    # Load presets from parameters
    parameter = self.getParameterNode()

    # Set the volume node
    self._isLoadingState = True
    self.setVolumeNode(slicer.mrmlScene.GetNodeByID(parameter.GetParameter("VolumeNodeID")))
    self.applyState()
    self._isLoadingState = False
    self._refresh3DView()

  def applyState(self):
    """Override from RFViewerWidget"""
    oldLoadingState = self._isLoadingState
    self._isLoadingState = True
    parameter = self.getParameterNode()

    # Apply layout
    self.ui.layoutSelector.setCurrentIndex(int(parameter.GetParameter("CurrentLayout")))

    # Get correct 2D and 3D presets
    industry = IndustryType(int(parameter.GetParameter("IndustryType")))
    if industry == self.industry:
      preset3D = self._vrLogic.GetPresetByName(parameter.GetParameter("CurrentPreset3D"))
      preset2D = parameter.GetParameter("CurrentPreset2D")
    else:
      warningMessageBox(self.tr("Loading from different industry type"), self.tr(
        "Session was saved with a different industry type. It will be loaded using current default industry type presets."))
      preset3D = self._defaultIndustry3DPreset()
      preset2D = self._defaultIndustry2DPreset()

    # Apply 3D preset
    self.ui.preset3DSelector.setCurrentNode(preset3D)

    # Apply color
    try:
      self._selectItemWithInputData(self.ui.colorSelector, int(parameter.GetParameter("CurrentColor")))
    except ValueError:  # Default 3D preset color
      self.ui.colorSelector.setCurrentIndex(0)

    # Apply threshold
    self.ui.shiftSlider.value = float(parameter.GetParameter("CurrentThreshold"))

    # Apply 2D preset
    self.ui.preset2DSelector.setCurrentText(preset2D)

    # Apply VRMode
    self._selectItemWithInputData(self.ui.vrModeSelector, int(parameter.GetParameter("CurrentVRMode")))
    self._isLoadingState = oldLoadingState

  @staticmethod
  def _selectItemWithInputData(selector, data):
    """
    Set selector index to the first item which has the input data value.
    """
    for i in range(selector.count):
      if selector.itemData(i) == data:
        selector.setCurrentIndex(i)
        break

  def _refresh3DView(self):
    """
    3D View volume rendering may not show on loading when other models are visible on integrated graphics cards.
    Disable the visibility of every model to enable VR loading and reactivate the visibility.
    """

    # Get display element states
    self._displayNodeVisibility = {d: d.GetVisibility3D() for d in slicer.mrmlScene.GetNodes() if
                                   isinstance(d, slicer.vtkMRMLDisplayNode)}
    self._roisVisibility = {r: r.GetDisplayVisibility() for r in
                            list(slicer.mrmlScene.GetNodesByClass('vtkMRMLAnnotationROINode'))}
    self._viewVisibility = {v: v.GetWidgetVisible() for v in list(slicer.util.getNodesByClass('vtkMRMLSliceNode'))}

    # Disable visibility everywhere
    self._disable3DVisibility()

    # Enable visibility for the VR only
    self.getVolumeDisplayNode3D().SetVisibility3D(True)

    # Restore visibility (wrapped in QTimer to execute after VR only is displayed)
    qt.QTimer.singleShot(0, self._restore3DVisibility)

  def _restore3DVisibility(self, forcedVisibilityValue=None):
    """
    Restores visibility for the three input visibility dictionaries if forcedVisibilityValue is None
    Otherwise forces the visibility to the given input visibility value
    """

    def isVisible(state):
      return state if forcedVisibilityValue is None else forcedVisibilityValue

    for d, previous_state in self._displayNodeVisibility.items():
      d.SetVisibility3D(isVisible(previous_state))

    for r, previous_state in self._roisVisibility.items():
      r.SetDisplayVisibility(isVisible(previous_state))

    for v, previous_state in self._viewVisibility.items():
      v.SetWidgetVisible(isVisible(previous_state))

  def _disable3DVisibility(self):
    self._restore3DVisibility(forcedVisibilityValue=False)
