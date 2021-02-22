import logging

import ctk
import qt
import slicer
from slicer.ScriptedLoadableModule import *

from RFViewerHomeLib import translatable, RFViewerWidget, removeNodeFromMRMLScene, createButton, showVolumeOnSlices, \
    wrapInQTimer, WindowLevelUpdater, Signal, nodeID, getNodeByID, toggleCheckBox, strToBool
from RFVisualizationLib import setNodeVisibleInMainViewsOnly, ViewTag


class RFSegmentation(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RF Segmentation"
        self.parent.categories = ["RFCo"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


@translatable
class RFSegmentationUI(qt.QWidget):
    """
    Widget responsible for airway segmentation. Uses Slicer segmentation widget and only exposes a few of the tools
    available.
    Resamples the source volume if the source volume is too big to be segmented by the available tools.

    Derives from QWidget to enable toggling the displayed volume in the 2D views on widget hide / show events.
    """

    def __init__(self, parent):
        qt.QWidget.__init__(self, parent)

        self._volumeNode = None
        self._resampledVolumeNode = None

        # Initialize resampled volume name in the MRML Scene
        # GetUniqueNameByString may add an underscore to the name given the circumstances. The first call makes sure the
        # following names are consistent
        self._resampledVolumeName = "SegmentationVolume"
        slicer.mrmlScene.GetUniqueNameByString(self._resampledVolumeName)

        self._segmentationVolumeNode = None
        self._windowLevelUpdater = None
        self._resampleCLI = None

        settings = qt.QSettings()
        settings.beginGroup("Segmentations")
        self._segmentNode = None
        self._segmentModifiedObserver = None
        self._segmentNodeName = "AirwaySegment"
        self._segmentColor = qt.QColor(settings.value("SegmentColor", "#1dd813"))
        self._maxSegmentVolumeSize = float(settings.value("MaximumPixelNumber", 30e6))
        settings.endGroup()

        self._progressText = self.tr("Initializing segmentation...")
        self.addProgressBar = Signal("str")
        self.removeProgressBar = Signal("str")

        self._segmentUi = slicer.util.getModuleGui(slicer.modules.segmenteditor)
        self._segmentationWidget = slicer.util.findChild(self._segmentUi, "qMRMLSegmentEditorWidget")
        self._segmentationShow3dButton = slicer.util.findChild(self._segmentationWidget, "Show3DButton")
        self._segmentationShow3dButton.setText(self.tr("Show 3D"))
        self._segmentationShow3dButton.setToolTip(self.tr("Show segmented volume in 3D view"))

        self._showSegmentationButton = createButton(self.tr("Show Segmentation"), isCheckable=True)
        self._showSegmentationButton.connect("toggled(bool)", self.setSegmentVisible)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self._showSegmentationButton)
        layout.addWidget(self._segmentationShow3dButton)
        layout.addLayout(self.extractSegmentationToolButtonsFromSegmentationUI())
        layout.addWidget(slicer.util.findChild(self._segmentUi, "OptionsGroupBox"))
        self.setEnabled(False)

        # Update segmentation visibility on layout changed to make sure that the segmentation volume will be visible
        # when new 3D views are displayed (by default all the 3D views are not instantiated on startup)
        slicer.app.layoutManager().connect("layoutChanged(int)",
                                           lambda *_: self.updateSegmentationVolumeVisibilityInSlices())

    def extractSegmentationToolButtonsFromSegmentationUI(self):
        """Extract the segmentation effects from the segmentation widget UI"""
        layout = ctk.ctkFlowLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.setAlignment(qt.Qt.AlignJustify)
        layout.alignItems = False
        layout.preferredExpandingDirections = qt.Qt.Vertical

        # Define segmentation buttons QObject name -> translation dictionary
        # Keep the translation strings as pure Python strings for LUpdate parsing compatibility
        segmentationButtons = {  #
            "NULL": self.tr("None"),  #
            "Threshold": self.tr("Threshold"),  #
            "Paint": self.tr("Paint"),  #
            "Erase": self.tr("Erase"),  #
            "Islands": self.tr("Islands"),  #
            "Fast Marching": self.tr("Fast Marching"),  #
            "Scissors": self.tr("Scissors")  #
        }

        for buttonName, buttonText in segmentationButtons.items():
            try:
                button = slicer.util.findChild(self._segmentUi, buttonName)
                button.text = buttonText
                button.toolTip = buttonText
                layout.addWidget(button)
            except RuntimeError:
                logging.error("Failed to load segmentation module {}".format(buttonName))

        return layout

    def setVolumeNode(self, volumeNode):
        """When the input volume node changes, initialize the segmentation volume node and the associated segments"""
        self.setEnabled(False)
        removeNodeFromMRMLScene(self._resampledVolumeNode)
        self._resampledVolumeNode = None
        self._segmentationVolumeNode = None
        self._windowLevelUpdater = None

        self.setEnabled(False)
        self.cancelResampleCLI()
        self._volumeNode = volumeNode

        if self.isVisible():
            self._initializeSegmentationNodeIfNecessary()

    @wrapInQTimer
    def updateSegmentationVolumeVisibilityInSlices(self):
        """
        Update the visibility of the segmentation volume node in the 3D and 2D views depending on the widget visibility
        """
        if None in [self._segmentationVolumeNode, self._volumeNode]:
            return

        # Update panorama view (segmentation volume may be wrongly displayed there on load)
        slicer.modules.RFPanoramaWidget.updateSliceDisplayedVolume()

        # Set either segmentation volume or volume node in 2D views depending on widget visibility
        volumeToShow = self._segmentationVolumeNode if self.isVisible() else self._volumeNode
        showVolumeOnSlices(volumeToShow.GetID(), ViewTag.mainViewTags())

    def onResampleCLIModified(self, cliNode, _):
        """If the resampling CLI is done, trigger the airway segment creation method"""
        if cliNode.GetStatusString() == "Scheduled":
            self.addProgressBar.emit(self._progressText)

        if cliNode.GetStatusString() == "Completed":
            self._onResamplingDone()

    def _initializeSegmentationNodeIfNecessary(self):
        """Initialize segmentation volume node if it hasn't been initialized yet"""
        if self._segmentationVolumeNode is None and self._volumeNode is not None:
            self._initializeSegmentationVolumeNode()
            self.updateSegmentationVolumeVisibilityInSlices()

    def _initializeSegmentationVolumeNode(self):
        """Resample the input volume node if necessary using the resample scalar CLI module"""
        dim = self._volumeNode.GetImageData().GetDimensions()
        pixelSize = dim[0] * dim[1] * dim[2]
        if pixelSize <= self._maxSegmentVolumeSize:
            self._segmentationVolumeNode = self._volumeNode
            self._onResamplingDone()
            return

        resampledVolumeName = slicer.mrmlScene.GetUniqueNameByString(self._resampledVolumeName)
        slicer.modules.RFViewerHomeWidget.getDataLoader().addIgnoredVolumeName(resampledVolumeName)
        self._resampledVolumeNode = slicer.modules.volumes.logic().CloneVolumeWithoutImageData(slicer.mrmlScene,
                                                                                               self._volumeNode,
                                                                                               resampledVolumeName)
        self._resampledVolumeNode.SetUndoEnabled(True)
        self._segmentationVolumeNode = self._resampledVolumeNode

        newSpacingFactor = (pixelSize / self._maxSegmentVolumeSize) ** (1 / 3)
        newSpacing = [str(spacing * newSpacingFactor) for spacing in self._volumeNode.GetSpacing()]

        module = slicer.modules.resamplescalarvolume
        self._resampleCLI = slicer.cli.createNode(module)
        self._resampleCLI.SetUndoEnabled(True)
        self._resampleCLI.AddObserver(self._resampleCLI.StatusModifiedEvent, self.onResampleCLIModified)

        cliParam = {"outputPixelSpacing": ",".join(newSpacing),  #
                    "interpolationType": "linear",  #
                    "InputVolume": self._volumeNode.GetID(),  #
                    "OutputVolume": self._resampledVolumeNode.GetID()}

        self._resampleCLI = slicer.cli.run(module, self._resampleCLI, cliParam)

    def _onResamplingDone(self):
        """
        When the resampling is done, initialize the airway segment for the current segmentation volume node and
        enable the segmentation widget.
        """
        self.resetAirwaySegment()
        self._synchronizeSegmentationWindowLevel()
        self.updateSegmentationVolumeVisibilityInSlices()
        self.setEnabled(True)
        self.removeProgressBar.emit(self._progressText)

    def _synchronizeSegmentationWindowLevel(self):
        if None in [self._segmentationVolumeNode, self._volumeNode]:
            return

        if self._segmentationVolumeNode.GetID() != self._volumeNode.GetID():
            self._windowLevelUpdater = WindowLevelUpdater(self._volumeNode, self._segmentationVolumeNode)

    def getSegmentation(self):
        """Returns the segmentation node if it is present. Else returns None"""
        if not self._segmentNode:
            return None

        return self._segmentNode.GetSegmentation()

    def getDisplaySegmentationNode(self):
        """Returns the display segmentation node if it is present. Else returns None"""
        if not self._segmentNode:
            return None

        return self._segmentNode.GetDisplayNode()

    def getSegmentationNode(self):
        """Returns the segmentation node if it is present. Else returns None"""
        return self._segmentNode

    def getAirwaySegment(self):
        """Returns airway segment if the segmentation node is present. Else returns None"""
        segmentation = self.getSegmentation()
        if not segmentation:
            return None
        return self.getSegmentation().GetSegment(self._segmentNodeName)

    def resetAirwaySegment(self):
        """Create a new segmentation node with one airway segment for the current segment volume node"""
        # Remove previous segment node
        removeNodeFromMRMLScene(self._segmentNode)

        # Create new segment node
        self._segmentNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', self._segmentNodeName)
        self._segmentNode.SetUndoEnabled(True)
        self._segmentationWidget.setSegmentationNode(self._segmentNode)
        setNodeVisibleInMainViewsOnly(self._segmentNode)

        # Set segmentation master volume
        self._segmentationWidget.setMasterVolumeNode(self._segmentationVolumeNode)

        # Add airway segment
        self.getSegmentation().AddEmptySegment(self._segmentNodeName)
        segment = self.getAirwaySegment()
        segment.ColorAutoGeneratedOff()
        segment.SetColor(self._segmentColor.redF(), self._segmentColor.greenF(), self._segmentColor.blueF())

        # Set airway segment as selected segment
        self._segmentationWidget.setCurrentSegmentID(self._segmentNodeName)
        self.setSegmentVisible(True)

    def setSegmentVisible(self, isVisible):
        """Toggles segment visibility in the 2D and 3D views"""
        if not self._segmentNode:
            return

        self._showSegmentationButton.setChecked(isVisible)
        self._segmentNode.GetDisplayNode().SetSegmentVisibility(self._segmentNodeName, isVisible)

        if not isVisible:
            self._segmentationShow3dButton.setChecked(False)

    def showEvent(self, event):
        """On show event, show the segmentation volume from the slices"""
        qt.QWidget.showEvent(self, event)
        self._initializeSegmentationNodeIfNecessary()
        self.updateSegmentationVolumeVisibilityInSlices()

    def hideEvent(self, event):
        """On hide event, hide the segmentation volume from the slices"""
        qt.QWidget.hideEvent(self, event)
        self.updateSegmentationVolumeVisibilityInSlices()

    def cancelResampleCLI(self):
        if self._resampleCLI is not None:
            self._resampleCLI.Cancel()
            removeNodeFromMRMLScene(self._resampleCLI)
            self._resampleCLI = None

    def saveToParameterNode(self, parameter):
        parameter.SetParameter("VolumeID", nodeID(self._volumeNode))
        parameter.SetParameter("ResampledVolumeID", nodeID(self._resampledVolumeNode))
        parameter.SetParameter("SegmentationVolumeID", nodeID(self._segmentationVolumeNode))
        parameter.SetParameter("SegmentNodeID", nodeID(self._segmentNode))
        parameter.SetParameter("SegmentationVisible", str(self._showSegmentationButton.checked))
        parameter.SetParameter("Segmentation3DVisible", str(self._segmentationShow3dButton.checked))

    def loadFromParameterNode(self, parameter):
        # Load segmentation nodes
        self._volumeNode = getNodeByID(parameter.GetParameter("VolumeID"))
        self._resampledVolumeNode = getNodeByID(parameter.GetParameter("ResampledVolumeID"))
        self._segmentationVolumeNode = getNodeByID(parameter.GetParameter("SegmentationVolumeID"))
        self._segmentNode = getNodeByID(parameter.GetParameter("SegmentNodeID"))

        # Synchronize segmentation widget
        if not self._segmentNode:
            return

        self._segmentationWidget.setSegmentationNode(self._segmentNode)
        self._segmentationWidget.setMasterVolumeNode(self._segmentationVolumeNode)
        self._segmentationWidget.setCurrentSegmentID(self._segmentNodeName)

        # Synchronize window levels
        self._synchronizeSegmentationWindowLevel()

        # Update visibility
        self.updateSegmentationVolumeVisibilityInSlices()

        # Enable segmentation panel
        self.setEnabled(True)
        self._segmentationShow3dButton.setEnabled(True)

        # Toggle show segmentation and 3D
        segmentationVisible = strToBool(parameter.GetParameter("SegmentationVisible"))
        segmentation3DVisible = strToBool(parameter.GetParameter("Segmentation3DVisible"))
        toggleCheckBox(self._showSegmentationButton, lastCheckedState=segmentationVisible)

        # Toggle show 3D only if visible in the session as showing the 3D view can be time consuming
        if segmentation3DVisible:
            toggleCheckBox(self._segmentationShow3dButton, lastCheckedState=segmentation3DVisible)
        else:
            self._segmentationShow3dButton.setChecked(segmentation3DVisible)


class RFSegmentationWidget(RFViewerWidget):
    """
    Humble object delegating to RFSegmentationUI class. Enables instantiation of the Widget as a Slicer Module
    """

    def __init__(self, parent=None):
        RFViewerWidget.__init__(self, parent)
        self._ui = None

    def setup(self):
        RFViewerWidget.setup(self)
        self.setupUI()

    @wrapInQTimer
    def setupUI(self):
        self._ui = RFSegmentationUI(self.layout.parentWidget())
        self._ui.addProgressBar.connect(self.addProgressBar.emit)
        self._ui.removeProgressBar.connect(self.removeProgressBar.emit)

        self.layout.addWidget(self._ui)
        self.layout.addStretch()

    def setVolumeNode(self, volumeNode):
        """Override from RFViewerWidget"""
        self._ui.setVolumeNode(volumeNode)

    def clean(self):
        """Override from RFViewerWidget"""
        self._ui.cancelResampleCLI()

    def onSessionAboutToBeSaved(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        self._ui.saveToParameterNode(parameter)

    def onSessionLoaded(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        self._ui.loadFromParameterNode(parameter)

    def saveState(self):
        """Override from RFViewerWidget"""
        self._ui.saveToParameterNode(self.getParameterNode())

    def applyState(self):
        """Override from RFViewerWidget"""
        self._ui.loadFromParameterNode(self.getParameterNode())

    def __getattr__(self, name):
        """
        Delegate all calls not defined in the RFViewerWidget class to RFSegmentationUI object
        """
        return getattr(self._ui, name)


class RFSegmentationLogic(ScriptedLoadableModuleLogic):
    """Empty logic class for the module to avoid error report on module loading"""
    pass
