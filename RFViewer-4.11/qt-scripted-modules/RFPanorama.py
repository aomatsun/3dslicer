import qt
import slicer
from slicer.ScriptedLoadableModule import *

from RFPanoramaLib import CurvedPlanarReformatLogic
from RFViewerHomeLib import translatable, RFViewerWidget, createButton, removeNodeFromMRMLScene, horizontalSlider, \
    showVolumeOnSlices, WindowLevelUpdater, nodeID, getNodeByID
from RFVisualizationLib import RFLayoutType, ViewTag


class RFPanorama(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RF Viewer Panorama"
        self.parent.categories = ["RFCo"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


@translatable
class RFPanoramaWidget(RFViewerWidget):
    """
    Widget responsible for creating and displaying a panoramic view base on a curve markup.
    Uses the CurvedPlanarReformat module of SlicerSandbox.
    """

    def __init__(self, parent=None):
        RFViewerWidget.__init__(self, parent)
        self._volumeNode = None
        self._curvedReformatLogic = CurvedPlanarReformatLogic()
        self._straightenTransformNode = None
        self._straightenedVolume = None
        self._windowLevelUpdater = None

        self._curveResolutionSlider = horizontalSlider(value=0.5, minimum=0.1, maximum=10,
                                                       toolTip=self.tr("Sampling distance along the curve (mm)"))
        self._sliceResolutionSlider = horizontalSlider(value=0.5, minimum=0.1, maximum=10,
                                                       toolTip=self.tr("Pixel resolution of the panorama image (mm)"))
        self._panoramaHeightSlider = horizontalSlider(value=80, minimum=10, maximum=200, singleStep=1, pageStep=1,
                                                      toolTip=self.tr("Height of the panorama image (mm)"))
        self._panoramaDepthSlider = horizontalSlider(value=40, minimum=10, maximum=100, singleStep=1, pageStep=1,
                                                     toolTip=self.tr("Depth of the panorama image (mm)"))

        # Initialize straightened volume name in the MRML Scene
        # GetUniqueNameByString may add an underscore to the name given the circumstances. The first call makes sure the
        # following names are consistent
        self._straightenedVolumeName = "PanoramicStraightenedVolume"
        slicer.mrmlScene.GetUniqueNameByString(self._straightenedVolumeName)

    def setup(self):
        RFViewerWidget.setup(self)

        advancedForm = qt.QFormLayout()
        advancedForm.addRow(self.tr("Curve Resolution (mm)"), self._curveResolutionSlider)
        advancedForm.addRow(self.tr("Slice Resolution (mm)"), self._sliceResolutionSlider)
        advancedForm.addRow(self.tr("Panorama Height (mm)"), self._panoramaHeightSlider)
        advancedForm.addRow(self.tr("Panorama Depth (mm)"), self._panoramaDepthSlider)

        self.layout.addLayout(advancedForm)
        self.layout.addWidget(createButton(self.tr("Panoramic View"), self.showPanoramicView))
        self.layout.addStretch()

    def setVolumeNode(self, volumeNode):
        """
        On new volume node, save the new node for panoramic view, remove the previously straightened volume if any
        and update the 2D slices to avoid the panoramic views from displaying the new volume.
        """
        self._volumeNode = volumeNode

        removeNodeFromMRMLScene(self._straightenedVolume)
        self._straightenedVolume = None
        self._windowLevelUpdater = None

        self.updateSliceDisplayedVolume()

    def showPanoramicView(self):
        curveNode = self.getCurveNode()
        if None in [self._volumeNode, curveNode]:
            return

        self.straightenVolumeNodeAlongCurve(curveNode)
        self.showStraightenedVolume()

    def straightenVolumeNodeAlongCurve(self, curveNode):
        if self._straightenTransformNode is None:
            self._straightenTransformNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTransformNode',
                                                                               'Straightening transform')

        sliceSizeMm = [self._panoramaDepthSlider.value, self._panoramaHeightSlider.value]
        spacingAlongCurveMm = self._curveResolutionSlider.value
        sliceResolutionMm = self._sliceResolutionSlider.value
        outputSpacing = [sliceResolutionMm, sliceResolutionMm, spacingAlongCurveMm]

        self._curvedReformatLogic.computeStraighteningTransform(self._straightenTransformNode, curveNode, sliceSizeMm,
                                                                spacingAlongCurveMm)

        if self._straightenedVolume is None:
            straightenedName = slicer.mrmlScene.GetUniqueNameByString(self._straightenedVolumeName)
            slicer.modules.RFViewerHomeWidget.getDataLoader().addIgnoredVolumeName(straightenedName)
            self._straightenedVolume = slicer.modules.volumes.logic().CloneVolumeWithoutImageData(slicer.mrmlScene,
                                                                                                  self._volumeNode,
                                                                                                  straightenedName)
            self._windowLevelUpdater = WindowLevelUpdater(self._volumeNode, self._straightenedVolume)

        self._curvedReformatLogic.straightenVolume(self._straightenedVolume, self._volumeNode, outputSpacing,
                                                   self._straightenTransformNode)
        self._windowLevelUpdater.synchroniseDisplayWithVolume()

    def showStraightenedVolume(self):
        slicer.modules.RFVisualizationWidget.setSlicerLayout(RFLayoutType.RFPanoramaLayout)
        self.updateSliceDisplayedVolume()
        slicer.modules.RFVisualizationWidget.fitSlicesToBackground()

    def updateSliceDisplayedVolume(self):
        # Display straightened volume
        showVolumeOnSlices(nodeID(self._straightenedVolume), ViewTag.panoramicViewTags())

        # Force the Axial, Coronal and Sagittal views to display the original volume (slices will switch automatically
        # to straightened volume when it's created due to the volume module logic)
        showVolumeOnSlices(nodeID(self._volumeNode), ViewTag.mainViewTags())

    @staticmethod
    def getCurveNode():
        nodes = slicer.util.getNodesByClass('vtkMRMLMarkupsCurveNode')
        if len(nodes) > 0:
            return nodes[0]
        return None

    def onSessionAboutToBeSaved(self):
        """Override from RFViewerWidget"""
        self.saveState()

    def onSessionLoaded(self):
        """Override from RFViewerWidget"""
        self.applyState()

    def saveState(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        parameter.SetParameter("VolumeID", nodeID(self._volumeNode))
        parameter.SetParameter("StraightenedTransformID", nodeID(self._straightenTransformNode))
        parameter.SetParameter("StraightenedVolumeID", nodeID(self._straightenedVolume))

    def applyState(self):
        """Override from RFViewerWidget"""
        parameter = self.getParameterNode()
        self._volumeNode = getNodeByID(parameter.GetParameter("VolumeID"))
        self._straightenTransformNode = getNodeByID(parameter.GetParameter("StraightenedTransformID"))
        self._straightenedVolume = getNodeByID(parameter.GetParameter("StraightenedVolumeID"))

        if None not in [self._volumeNode, self._straightenedVolume]:
            self._windowLevelUpdater = WindowLevelUpdater(self._volumeNode, self._straightenedVolume)
            self._windowLevelUpdater.synchroniseDisplayWithVolume()

        self.updateSliceDisplayedVolume()


class RFPanoramaLogic(ScriptedLoadableModuleLogic):
    """Empty logic class for the module to avoid error report on module loading"""
    pass
