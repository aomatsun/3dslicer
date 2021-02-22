import vtk, qt, slicer
from slicer.ScriptedLoadableModule import *
from RFAnnotationLib import RFLineProfileWidget
from RFAnnotationLib import RFAnnotationCanalWidget
from RFViewerHomeLib import RFViewerWidget, jumpSlicesToNthMarkupPosition, removeNodeFromMRMLScene, getNodeByID, \
  translatable
from RFVisualizationLib import setNodeVisibleInMainViewsOnly


class RFAnnotation(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "RFAnnotation"
    self.parent.categories = ["RFCo"]
    self.parent.dependencies = []
    self.parent.contributors = []
    self.parent.helpText = ""


@translatable
class RFAnnotationWidget(RFViewerWidget):
  def __init__(self, parent=None):
    RFViewerWidget.__init__(self, parent)
    settings = qt.QSettings()
    settings.beginGroup("Annotation")
    self.glyphScale = settings.value("MarkupGlyphScale", 3.0)
    self.textScale = settings.value("MarkupTextScale", 4.0)
    self.color = qt.QColor(settings.value("MarkupColorHex", "#379ede"))
    settings.endGroup()

    self._widget = slicer.modules.markups.createNewWidgetRepresentation()
    self._widget.setMRMLScene(slicer.mrmlScene)
    self._translateAnnotationWidgets()

    self.canalWidget = RFAnnotationCanalWidget(parent)
    self.layout.addWidget(self.canalWidget)
    self.layout.addWidget(self._widget)

    # Add canal button into markups layout
    markupsHLayout = self._widget.findChild("QHBoxLayout", "horizontalLayout")
    markupsHLayout.addWidget(self.canalWidget.addCanalButton)

    # Add canal widget advanced parameters between markups layout and tree view
    markupsVLayout = self._widget.findChild("QVBoxLayout", "verticalLayout_2")
    markupsVLayout.insertWidget(1, self.canalWidget)

    self.buttonCurve = self._widget.findChild('QPushButton', 'createOpenCurvePushButton')
    self.treeView = None
    self.connectSubjectHierarchy()

    self.updateCurveButtonState()
    self.updateWidgetUI()
    self.connectActions()

    self.lineProfileWidget = RFLineProfileWidget(parent)
    self.layout.addWidget(self.lineProfileWidget)

    self._volumeNode = None

  def _translateAnnotationWidgets(self):
    # Translate node buttons
    slicer.util.findChild(self._widget, "createLabel").setText(self.tr("Create:"))
    slicer.util.findChild(self._widget, "createLinePushButton").setToolTip(self.tr("Create ruler measurement"))
    slicer.util.findChild(self._widget, "createAnglePushButton").setToolTip(self.tr("Create angle measurement"))
    slicer.util.findChild(self._widget, "createOpenCurvePushButton").setToolTip(
      self.tr("Create panorama reconstruction curve"))
    slicer.util.findChild(self._widget, "createLabel").hide()
    slicer.util.findChild(self._widget, "createLinePushButton").hide()
    slicer.util.findChild(self._widget, "createAnglePushButton").hide()
    slicer.util.findChild(self._widget, "createOpenCurvePushButton").hide()
    # Translate qMRMLSubjectHierarchyTreeView
    tree = slicer.util.findChild(self._widget, "activeMarkupTreeView")
    treeHeaderTranslations = [
      (self.tr("Node"), self.tr("Node name and type")),
      (self.tr("Description"), self.tr("Node description")),
      ("", self.tr("Show/Hide branch or node")),
      ("", self.tr("Node color")),
    ]

    for i_header, (headerText, headerTooltip) in enumerate(treeHeaderTranslations):
      headerItem = tree.model().horizontalHeaderItem(i_header)
      headerItem.setText(headerText)
      headerItem.setToolTip(headerTooltip)

  def connectSubjectHierarchy(self):
    self.treeView = self._widget.findChild('qMRMLSubjectHierarchyTreeView', 'activeMarkupTreeView')
    self.treeView.connect('currentItemChanged(vtkIdType)', self.onCurrentSelectedMarkupChanged)
    self.treeView.subjectHierarchyNode().AddObserver(
      slicer.vtkMRMLSubjectHierarchyNode.SubjectHierarchyItemRemovedEvent, self.removeItem)

  def removeItem(self, *args):
    self.lineProfileWidget.setMarkupNode(None)
    self.canalWidget.deleteCanal()

  def __del__(self):
    slicer.mrmlScene.RemoveObserver(self.nodeRemovedObserverTag)
    slicer.mrmlScene.RemoveObserver(self.nodeAddedObserverTag)

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

  def setVolumeNode(self, volumeNode):
    self._volumeNode = volumeNode
    self.lineProfileWidget.logic.setInputVolumeNode(volumeNode)

  def onCurrentSelectedMarkupChanged(self, itemId):
    currentMarkup = self.treeView.subjectHierarchyNode().GetItemDataNode(self.treeView.currentItem())
    if currentMarkup is not None:
      self.lineProfileWidget.setMarkupNode(currentMarkup)
      jumpSlicesToNthMarkupPosition(markupNode=currentMarkup, i_nthMarkup=0, centerToLocation=False)

      selectedCanal = None
      if isinstance(currentMarkup, slicer.vtkMRMLMarkupsFiducialNode):
        selectedCanal = currentMarkup
      self.canalWidget.selectCanal(selectedCanal)

  def updateWidgetUI(self):
    """
    Update the default widget by hidding/adding new ui elements
    """
    collapsibleButtons = self._widget.findChildren('ctkCollapsibleButton')
    for button in collapsibleButtons:
      button.hide()

    removedButtonsNames = ['createFiducialPushButton', 'createClosedCurvePushButton', 'createPlanePushButton']
    for buttonName in removedButtonsNames:
      button = self._widget.findChild('QPushButton', buttonName)
      if button is not None:
        button.hide()

  def connectActions(self):
    """
    Define all actions/connections for this module
    """
    self.nodeRemovedObserverTag = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeRemovedEvent, self.nodeRemoved)
    self.nodeAddedObserverTag = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeAddedEvent, self.nodeAdded)

    markupsButtonsName = ['createLinePushButton', 'createAnglePushButton', 'createOpenCurvePushButton']
    for buttonName in markupsButtonsName:
      button = self._widget.findChild('QPushButton', buttonName)
      if button is not None:
        button.clicked.connect(self.onMarkupButtonClick)

  def nodeRemoved(self, *args):
    self.updateCurveButtonState()

  def onMarkupButtonClick(self):
    self.canalWidget.hideOptions()

  @vtk.calldata_type(vtk.VTK_OBJECT)
  def nodeAdded(self, caller, event, newNode):
    if isinstance(newNode, slicer.vtkMRMLMarkupsNode):
      newNode.SetUndoEnabled(True)
      setNodeVisibleInMainViewsOnly(newNode)
      displayNode = newNode.GetDisplayNode()

      if displayNode is not None:
        displayNode.SetUseGlyphScale(True)
        displayNode.SetGlyphScale(self.glyphScale)
        displayNode.SetTextScale(self.textScale)
        displayNode.SetSelectedColor(self.color.redF(), self.color.greenF(), self.color.blueF())

    # Force curve nodes to be Kochanek Splines for smoother curve
    if isinstance(newNode, slicer.vtkMRMLMarkupsCurveNode):
      newNode.SetUndoEnabled(True)
      newNode.SetCurveTypeToKochanekSpline()

    self.updateCurveButtonState()

  def updateCurveButtonState(self):
    """
    Update button curve enable status
    """
    if self.buttonCurve is None:
      return

    # Only enable one curve node at a time
    nbCurveMarkups = len(slicer.util.getNodesByClass('vtkMRMLMarkupsCurveNode'))
    self.buttonCurve.setEnabled(nbCurveMarkups == 0)

  def onSessionAboutToBeSaved(self):
    """Override from RFViewerWidget"""
    parameter = self.getParameterNode()
    parameter.SetParameter("VolumeID", self._volumeNode.GetID())
    self.saveState()

  def saveState(self):
    """Override from RFViewerWidget"""

    parameter = self.getParameterNode()

    lineProfileWidgetParam = self.lineProfileWidget.getParameterDict()
    for key, param in lineProfileWidgetParam.items():
      parameter.SetParameter(key, param)

    canalParameters = self.canalWidget.getParameterDict()
    for key, param in canalParameters.items():
      parameter.SetParameter(key, param)

  def onSessionLoaded(self):
    """Override from RFViewerWidget"""
    # Reconnect subject hierarchy tree as it depends on node which was reloaded in the scene
    self.connectSubjectHierarchy()

    # Load module
    parameter = self.getParameterNode()

    # Setup line profile
    # Info: Need to recreate the whole line profile logic because of the behavior
    # of the PlotSerie. When loaded a session, then the GetName() of the PlotSeries doesn't
    # work properly. Even if we set the correct name, the name displayed in the chart is not
    # the correct one
    removeNodeFromMRMLScene(getNodeByID(parameter.GetParameter("PlotSerieID")))
    removeNodeFromMRMLScene(getNodeByID(parameter.GetParameter("TableID")))
    removeNodeFromMRMLScene(getNodeByID(parameter.GetParameter("PlotChartID")))

    nodes = slicer.util.getNodesByClass("vtkMRMLMarkupsLineNode")
    markupNode = None
    if len(nodes) > 0:
      markupNode = nodes[0]

    self.lineProfileWidget.reinitialize(markupNode)

    # Setup current volume
    self.setVolumeNode(getNodeByID(parameter.GetParameter("VolumeID")))
    self.applyState()

  def applyState(self):
    """Override from RFViewerWidget"""
    parameter = self.getParameterNode()

    # Load canals
    canalParameters = {}

    for name in parameter.GetParameterNames():
      if name not in ["PlotSerieID", "TableID", "PlotChartID", "VolumeID"]:
        canalParameters[name] = parameter.GetParameter(name)

    self.canalWidget.loadFromParameterDict(canalParameters)
