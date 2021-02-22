import vtk, qt, slicer, os

from RFViewerHomeLib import translatable
from RFAnnotationLib import RFCanal
import json

#
# RFAnnotationCanal
#
@translatable
class RFAnnotationCanalWidget(qt.QWidget):

  def __init__(self, parent=None):
    qt.QWidget.__init__(self, parent)

    self.logic = RFAnnotationCanalLogic()
    self.canals = {}
    self.currentCanal = None
    self.defaultRadius = 1.0

    # Create button used to create a new canal
    self.addCanalButton = qt.QPushButton(self.icon(), '')
    self.addCanalButton.checkable = True
    self.addCanalButton.setToolTip(self.tr('Draw canal'))
    self.addCanalButton.clicked.connect(self.onClickAddCanalButton)
    self.addCanalButton.hide()
    self.setupOptionsFrame()
    self.layoutIntermediate = qt.QFormLayout()
    self.layoutIntermediate.addWidget(self.optionsWidget)

    self.setLayout(self.layoutIntermediate)

    # Add remove node observer to cleanup the canals which have been deleted from the subject hierarchy tree
    self._removeNodeObserver = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeRemovedEvent,
                                                            self._onSceneNodeRemoved)

  def __del__(self):
    slicer.mrmlScene.RemoveObserver(self._removeNodeObserver)

  @vtk.calldata_type(vtk.VTK_OBJECT)
  def _onSceneNodeRemoved(self, caller, event, removedNode):
    """If canal markup node was removed from scene, remove the associated canal and model"""
    nodeId = removedNode.GetID()
    if nodeId in self.canals:
      if self.currentCanal and self.currentCanal.getID() == nodeId:
        self.currentCanal = None

      canal = self.canals[nodeId]
      canal.deleteFromScene()
      self.canals.pop(nodeId)

  def icon(self):
    iconPath = os.path.join(os.path.dirname(__file__), 'CanalIcon.png')
    if os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    return qt.QIcon()

  def setupOptionsFrame(self):
    self.optionsLayout = qt.QFormLayout()

    # Fiducial Placement widget
    self.fiducialPlacementToggle = slicer.qSlicerMarkupsPlaceWidget()
    self.fiducialPlacementToggle.setMRMLScene(slicer.mrmlScene)
    self.fiducialPlacementToggle.placeMultipleMarkups = self.fiducialPlacementToggle.ForcePlaceMultipleMarkups
    self.fiducialPlacementToggle.buttonsVisible = False
    self.fiducialPlacementToggle.show()
    self.fiducialPlacementToggle.placeButton().show()
    self.fiducialPlacementToggle.deleteButton().show()
    self.fiducialPlacementToggle.interactionNode().AddObserver(
      slicer.vtkMRMLInteractionNode.EndPlacementEvent, self.onEndPlacingFiducial
    )

    # Radius spinbox
    self.radiusSpinBox = slicer.qMRMLSpinBox()
    self.radiusSpinBox.value = self.defaultRadius
    self.radiusSpinBox.quantity = 'length'
    self.radiusSpinBox.unitAwareProperties = slicer.qMRMLSpinBox.MaximumValue | slicer.qMRMLSpinBox.Precision | slicer.qMRMLSpinBox.Prefix | slicer.qMRMLSpinBox.Suffix
    self.radiusSpinBox.connect('valueChanged(double)', self.onRadiusChanged)

    # Setup layout
    self.optionsLayout.addRow(self.fiducialPlacementToggle)
    self.optionsLayout.addRow(self.tr('Radius: '), self.radiusSpinBox)

    self.optionsWidget = qt.QWidget()
    self.optionsWidget.setLayout(self.optionsLayout)
    self.optionsWidget.hide()

  def selectCanal(self, node):
    self.hideOptions()
    if not node:
      self.currentCanal = None
      return

    self.currentCanal = self.canals.get(node.GetID(), None)
    if self.currentCanal:
        self.fiducialPlacementToggle.setPlaceModeEnabled(False)
        self.showOptions()
        self.updateUI(enablePlaceMode = False)

  def deleteCanal(self):
    if self.currentCanal is not None:
      canalID = self.currentCanal.getID()
      if canalID in self.canals:
        self.canals.pop(canalID)

      self.currentCanal.deleteFromScene()
      self.currentCanal = None

  def updateUI(self, enablePlaceMode = True):
    self.radiusSpinBox.value = self.currentCanal.radius
    self.logic.radius = self.currentCanal.radius
    self.fiducialPlacementToggle.setCurrentNode(self.currentCanal.markupNode)
    if enablePlaceMode is not None:
      self.fiducialPlacementToggle.setPlaceModeEnabled(enablePlaceMode)

  def hideOptions(self):
    self.addCanalButton.setChecked(False)
    self.optionsWidget.setVisible(False)
    # Remove persistency in order to avoid to add markup each time we left click
    self.fiducialPlacementToggle.setPlaceModePersistency(0)

  def showOptions(self):
    self.addCanalButton.setChecked(True)
    self.optionsWidget.setVisible(True)

  def onClickAddCanalButton(self):
    self.optionsWidget.setVisible(self.addCanalButton.isChecked())
    if self.addCanalButton.isChecked():
      newCanal = RFCanal(radius=self.defaultRadius)
      newCanal.generateCanal()
      self.currentCanal = newCanal
      self.canals[self.currentCanal.getID()] = self.currentCanal
      self.updateUI()

      self.currentCanal.markupPointsModifiedSignal.connect(self.onMarkupPointsModified)

  def onRadiusChanged(self, radius):
    self.currentCanal.radius = radius
    self.logic.radius = self.currentCanal.radius
    self.updateModelFromSegmentMarkupNode()

  def onMarkupPointsModified(self, canal):
    self.currentCanal = canal
    self.updateUI(enablePlaceMode=None)
    self.updateModelFromSegmentMarkupNode()

  def onEndPlacingFiducial(self, *args):
    if self.currentCanal is not None:
      self.hideOptions()

  def updateModelFromSegmentMarkupNode(self):
    if not self.currentCanal:
      return
    self.logic.updateModelFromMarkup(self.currentCanal.markupNode, self.currentCanal.modelNode)

  def getParameterDict(self):
    paramDict = {}
    for canalId, canal in self.canals.items():
      paramDict[canalId] = json.dumps(canal.getParameterDict())
    return paramDict

  def loadFromParameterDict(self, paramDict):
    self.currentCanal = None
    self.canals.clear()

    for key, val in paramDict.items():
      try:
        canal = RFCanal.createFromParameterDict(json.loads(val))
        canal.markupPointsModifiedSignal.connect(self.onMarkupPointsModified)
        self.canals[key] = canal
      except ValueError:
        pass


class RFAnnotationCanalLogic(object):

  def __init__(self):
    self.radius = 1.0
    self.numberOfLineSegmentsBetweenControlPoints = 15
    self.interpolationType = slicer.vtkMRMLMarkupsToModelNode.KochanekSpline
    self.polynomialFitType = slicer.vtkMRMLMarkupsToModelNode.MovingLeastSquares
    self.curveGenerator = slicer.vtkCurveGenerator()

  def updateModelFromMarkup(self, inputMarkup, outputModel):
    """
    Update model to enclose all points in the input markup list
    """
    markupsToModel = slicer.modules.markupstomodel.logic()
    tubeLoop = False
    tubeNumberOfSides = 8
    cleanMarkups = True
    polynomialOrder = 3
    # Create Canal from points
    markupsToModel.UpdateOutputCurveModel( inputMarkup, outputModel,
      self.interpolationType, tubeLoop, self.radius, tubeNumberOfSides, self.numberOfLineSegmentsBetweenControlPoints,
      cleanMarkups, polynomialOrder, slicer.vtkMRMLMarkupsToModelNode.RawIndices, self.curveGenerator,
      self.polynomialFitType )