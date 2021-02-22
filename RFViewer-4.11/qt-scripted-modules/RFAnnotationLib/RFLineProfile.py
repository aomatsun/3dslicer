import qt
import slicer
import vtk

from RFAnnotationLib import getLineResolutionFromLineLength, getOrCreateTableColumn, getCurrentLayout
from RFVisualizationLib import RFLayoutType
from RFViewerHomeLib import translatable, removeNodeFromMRMLScene, nodeID


#
# RFLineProfileWidget
#
@translatable
class RFLineProfileWidget(qt.QWidget):

  def __init__(self, parent=None):
    qt.QWidget.__init__(self, parent)
    self.logic = RFLineProfileLogic()
    mainLayout = qt.QFormLayout()

    #
    # Apply Button
    #
    self.applyButton = qt.QPushButton(self.tr("Show intensity profile"))
    self.applyButton.enabled = False
    mainLayout.addRow(self.applyButton)

    self.setLayout(mainLayout)

    # connections
    self.applyButton.connect('clicked(bool)', self.onApplyButton)

    # Refresh Apply button state
    self.enableApplyButton()

  def __del__(self):
    self.logic.setAutoUpdate(False)

  def reinitialize(self, markupNode):
    self.logic = RFLineProfileLogic()
    self.logic.setMarkupNode(markupNode)

    if getCurrentLayout() == RFLayoutType.RFLineProfileLayout:
      self.logic.showPlot()

  def getParameterDict(self):
    return {
      'PlotSerieID': nodeID(self.logic.plotSeriesNode),
      'TableID': nodeID(self.logic.tableNode),
      'PlotChartID': nodeID(self.logic.plotChartNode)
    }

  def enableApplyButton(self):
    self.applyButton.enabled = self.logic.getInputVolumeNode() and self.currentMarkupNode

  def onApplyButton(self):
    self.logic.showPlot()

  def setVolumeNode(self, node):
    self.logic.setInputVolumeNode(node)

  def setMarkupNode(self, node):
    self.currentMarkupNode = node
    self.enableApplyButton()
    self.logic.setMarkupNode(node)

#
# RFLineProfileLogic
#
@translatable
class RFLineProfileLogic(object):

  def __init__(self):
    self.inputVolumeNode = None
    self.markupNode = None
    self.markupObservation = None
    self.tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
    self.distanceArrayName = "Distance"
    self.intensityArrayName = "Intensity"

    self.plotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")

    self.plotChartNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode")
    self.plotChartNode.SetXAxisTitle(self.tr("Distance (mm)"))
    self.plotChartNode.SetYAxisTitle(self.tr("Intensity"))
    self.plotChartNode.AddAndObservePlotSeriesNodeID(self.plotSeriesNode.GetID())

  def __del__(self):
    self.setMarkupObservation(False)

  def setInputVolumeNode(self, volumeNode):
    self.inputVolumeNode = volumeNode
    self.update()

  def getInputVolumeNode(self):
    return self.inputVolumeNode

  def setMarkupNode(self, markupNode):
    if self.markupNode == markupNode:
      return

     # remove old observers
    self.setMarkupObservation(False)
    self.markupNode = markupNode

    if self.markupNode is not None:
      # add new observers
      self.setMarkupObservation(True)
      self.plotSeriesNode.SetName(self.markupNode.GetName())

    self.update()

  def update(self):
    if self.inputVolumeNode is None:
      return
    if self.markupNode is None:
      # reinitialize plot in order to show empty plot
      self.reinitializePlot()
    else:
      self.updateOutputTable()
    self.updatePlot()

    # We are already in plot view
    if getCurrentLayout() == slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpPlotView:
      # Reinitialize the view in order to fit the whole plot
      slicer.app.layoutManager().plotWidget(0).plotView().fitToContent()

  def setMarkupObservation(self, enable):
    if self.markupObservation:
      self.markupNode.RemoveObserver(self.markupObservation)
      self.markupObservation = None
    if enable and (self.markupNode is not None):
      self.markupObservation = self.markupNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onLineModified)

  def onLineModified(self, caller=None, event=None):
    self.update()

  def updatePlot(self):
    if self.plotSeriesNode is None:
      return
    # Create plot
    self.plotSeriesNode.SetAndObserveTableNodeID(self.tableNode.GetID())
    self.plotSeriesNode.SetXColumnName(self.distanceArrayName)
    self.plotSeriesNode.SetYColumnName(self.intensityArrayName)
    self.plotSeriesNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
    self.plotSeriesNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)
    self.plotSeriesNode.SetColor(0.0, 0.0, 0.9)

  def reinitializePlot(self):
    for columnName in [self.distanceArrayName, self.intensityArrayName]:
      getOrCreateTableColumn(self.tableNode, columnName).Initialize()

  def updateOutputTable(self):
    if self.markupNode.GetNumberOfDefinedControlPoints() < 2:
      self.tableNode.GetTable().SetNumberOfRows(0)
      return

    curvePoints_RAS = self.markupNode.GetCurvePointsWorld()
    isClosedCurve = self.markupNode.IsA('vtkMRMLClosedCurveNode')
    curveLengthMm = slicer.vtkMRMLMarkupsCurveNode.GetCurveLength(curvePoints_RAS, isClosedCurve)
    lineResolution = getLineResolutionFromLineLength(curveLengthMm)

    curvePoly_IJK = self._transformRASToIJK(curvePoints_RAS, self.inputVolumeNode)
    curvePoints_IJK = curvePoly_IJK.GetPoints()

    self._moveCurvePointsEndPointsToFitSingleSliceVolume(curvePoints_IJK, self.inputVolumeNode)

    samplingDistance = curveLengthMm / lineResolution
    probedPoints = self._probeVolumeAlongCurve(curvePoints_IJK, samplingDistance, isClosedCurve, self.inputVolumeNode)

    self._createArrayOfData(probedPoints, curveLengthMm)

  def showPlot(self):
    # Show plot in layout
    slicer.modules.RFVisualizationWidget.setSlicerLayout(RFLayoutType.RFLineProfileLayout)
    slicer.modules.plots.logic().ShowChartInLayout(self.plotChartNode)
    slicer.app.layoutManager().plotWidget(0).plotView().fitToContent()

  def _transformRASToIJK(self, curvePoints_RAS, volume):
    # Need to get the start/end point of the line in the IJK coordinate system
    # as VTK filters cannot take into account direction cosines
    # We transform the curve points from RAS coordinate system (instead of directly from the inputCurve coordinate system)
    # to make sure the curve is transformed to RAS exactly the same way as it is done for display.
    inputVolumeToIJK = vtk.vtkMatrix4x4()
    volume.GetRASToIJKMatrix(inputVolumeToIJK)
    rasToInputVolumeTransform = vtk.vtkGeneralTransform()
    slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(None, volume.GetParentTransformNode(), rasToInputVolumeTransform)
    rasToIJKTransform = vtk.vtkGeneralTransform()
    rasToIJKTransform.Concatenate(inputVolumeToIJK)
    rasToIJKTransform.Concatenate(rasToInputVolumeTransform)

    curvePoly_RAS = vtk.vtkPolyData()
    curvePoly_RAS.SetPoints(curvePoints_RAS)

    transformRasToIjk = vtk.vtkTransformPolyDataFilter()
    transformRasToIjk.SetInputData(curvePoly_RAS)
    transformRasToIjk.SetTransform(rasToIJKTransform)
    transformRasToIjk.Update()
    return transformRasToIjk.GetOutput()

  def _moveCurvePointsEndPointsToFitSingleSliceVolume(self, curvePoints_IJK, inputVolume):
    startPointIndex = 0
    endPointIndex = curvePoints_IJK.GetNumberOfPoints() - 1
    lineStartPoint_IJK = curvePoints_IJK.GetPoint(startPointIndex)
    lineEndPoint_IJK = curvePoints_IJK.GetPoint(endPointIndex)

    # Special case: single-slice volume
    # vtkProbeFilter treats vtkImageData as a general data set and it considers its bounds to end
    # in the middle of edge voxels. This makes single-slice volumes to have zero thickness, which
    # can be easily missed by a line that that is drawn on the plane (e.g., they happen to be
    # extremely on the same side of the plane, very slightly off, due to runding errors).
    # We move the start/end points very close to the plane and force them to be on opposite sides of the plane.
    dims = inputVolume.GetImageData().GetDimensions()
    for axisIndex in range(3):
      if dims[axisIndex] == 1:
        if abs(lineStartPoint_IJK[axisIndex]) < 0.5 and abs(lineEndPoint_IJK[axisIndex]) < 0.5:
          # both points are inside the volume plane
          # keep their distance the same (to keep the overall length of the line he same)
          # but make sure the points are on the opposite side of the plane (to ensure probe filter
          # considers the line crossing the image plane)
          pointDistance = max(abs(lineStartPoint_IJK[axisIndex]-lineEndPoint_IJK[axisIndex]), 1e-6)
          lineStartPoint_IJK[axisIndex] = -0.5 * pointDistance
          lineEndPoint_IJK[axisIndex] = 0.5 * pointDistance
          curvePoints_IJK.SetPoint(startPointIndex, lineStartPoint_IJK)
          curvePoints_IJK.SetPoint(endPointIndex, lineEndPoint_IJK)

  def _probeVolumeAlongCurve(self, curvePoints_IJK, samplingDistance, isClosedCurve, volumeNode):
    sampledCurvePoints_IJK = vtk.vtkPoints()
    slicer.vtkMRMLMarkupsCurveNode.ResamplePoints(curvePoints_IJK, sampledCurvePoints_IJK, samplingDistance, isClosedCurve)

    sampledCurvePoly_IJK = vtk.vtkPolyData()
    sampledCurvePoly_IJK.SetPoints(sampledCurvePoints_IJK)

    probeFilter = vtk.vtkProbeFilter()
    probeFilter.SetInputData(sampledCurvePoly_IJK)
    probeFilter.SetSourceData(volumeNode.GetImageData())
    probeFilter.ComputeToleranceOff()
    probeFilter.Update()

    return probeFilter.GetOutput()

  def _createArrayOfData(self, probedPoints, curveLengthMm):
    # Create arrays of data
    distanceArray = getOrCreateTableColumn(self.tableNode, self.distanceArrayName)
    intensityArray = getOrCreateTableColumn(self.tableNode, self.intensityArrayName)
    self.tableNode.GetTable().SetNumberOfRows(probedPoints.GetNumberOfPoints())
    x = range(0, probedPoints.GetNumberOfPoints())
    xStep = curveLengthMm/(probedPoints.GetNumberOfPoints()-1)
    probedPointScalars = probedPoints.GetPointData().GetScalars()
    for i in range(len(x)):
      distanceArray.SetValue(i, x[i]*xStep)
      intensityArray.SetValue(i, probedPointScalars.GetTuple(i)[0])
    distanceArray.Modified()
    intensityArray.Modified()
    self.tableNode.GetTable().Modified()

class RFLineProfileTest():
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_RFLineProfile1()

  def test_RFLineProfile1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")
    #
    # first, get some data
    #
    import SampleData
    sampleDataLogic = SampleData.SampleDataLogic()
    volumeNode = sampleDataLogic.downloadMRHead()

    logic = RFLineProfileLogic()

    self.delayDisplay('Test passed!')

