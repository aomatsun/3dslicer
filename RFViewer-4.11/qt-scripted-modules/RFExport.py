import os
from enum import IntEnum, unique
import subprocess
import sys
import ScreenCapture
import ctk
import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import *

from RFViewerHomeLib import RFViewerWidget, translatable, informationMessageBox, \
  warningMessageBox, TemporarySymlink, ExportDirectorySettings


@unique
class RFExportVolumeType(IntEnum):
  RFExportTIFF = 0
  RFExportRAW = 1


class RFExport(ScriptedLoadableModule):
  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "RFExport"
    self.parent.categories = ["RFCo"]
    self.parent.dependencies = []
    self.parent.contributors = []
    self.parent.helpText = ""


@translatable
class RFExportWidget(RFViewerWidget):
  def __init__(self, parent=None):
    RFViewerWidget.__init__(self, parent)
    self.dicomWrite = None
    self.patientItemID = None
    self.studyItemID = None
    self.volumeNode = None
    self.cap1 = None
    self.hierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    # Screenshot Export
    self.takeScreenshotButton = qt.QPushButton(
      qt.QIcon(':/Icons/ViewCapture.png'),
      self.tr('Take/save screenshot ...')
    )
    self.takeScreenshotButton.setToolTip(self.tr('Choose the path to save the file'))
    self.takeScreenshotButton.connect('clicked()', self.takeScreenshot)

    # DICOM Export
    self.exportDicomButton = qt.QPushButton(self.tr('DICOM'))
    self.exportDicomButton.setToolTip(self.tr('Export volume into dicom files'))
    self.exportDicomButton.connect('clicked()', self.exportVolumeToDicom)
    
    # DVD Export
    self.DVDexportButton = qt.QPushButton(self.tr('DVDexportButton'))
    self.DVDexportButton.setToolTip(self.tr('Export volume into dicom files'))
    self.DVDexportButton.connect('clicked()', self.DVDexport)
    
    # RAW Export
    self.exportRAWButton = qt.QPushButton(self.tr('RAW'))
    self.exportRAWButton.setToolTip(self.tr('Export volume to raw file'))
    self.exportRAWButton.connect('clicked()', self.exportVolumeToRaw)

    # TIFF Export
    self.exportTIFFButton = qt.QPushButton(self.tr('TIFF'))
    self.exportTIFFButton.setToolTip(self.tr('Export volume to TIFF file'))
    self.exportTIFFButton.connect('clicked()', self.exportVolumeToTIFF)

    # Segment Export
    self.exportSegmentButton = qt.QPushButton(self.tr('Export segment to stl'))
    self.exportSegmentButton.setToolTip(self.tr('Export segment node into stl file'))
    self.exportSegmentButton.connect('clicked()', self.exportSegmentToSTL)

    # Update layout
    self.layout.addWidget(self.takeScreenshotButton)
    self.layout.addWidget(self.exportDicomButton)
    self.layout.addWidget(self.exportRAWButton)
    self.layout.addWidget(self.exportTIFFButton)
    self.layout.addWidget(self.exportSegmentButton)

    # Temporary symlink for exports
    self._tmpSymLink = TemporarySymlink()
  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

  def setVolumeNode(self, node):
    if self.patientItemID is not None:
      self.hierarchyNode.RemoveItem(self.studyItemID)
      self.hierarchyNode.RemoveItem(self.patientItemID)
    self.volumeNode = node

  def takeScreenshot(self):
    """
    Take a screenshot of the full layout (3D + 2D views) and store as image
    """
    slicer.modules.annotations.showScreenshotDialog()
    # ScreenCapture.ScreenCaptureWidget()
    # self.logic = slicer.modules.annotations.logic()
    
    # path = qt.QFileDialog.getSaveFileName(None, self.tr('Save File'),
    #                        self.tr('Screenshot.png'), self.tr('Images (*.png *.jpg)'))
    # if not path:
    #   return
      
    # cap = ScreenCapture.ScreenCaptureLogic()
    # cap.showViewControllers(False)
    # cap.captureImageFromView(None, path)
    # cap.showViewControllers(True))
  def takeScreenshot1(self, path):
    """
    Take a screenshot of the full layout (3D + 2D views) and store as image
    """
    
    cap = ScreenCapture.ScreenCaptureLogic()
    cap.showViewControllers(False)
    self._captureImageFromView(self._tmpSymLink.getSymlinkToNewPath(path))
    cap.showViewControllers(True)

  @staticmethod
  def _captureImageFromView(filePath):
    """
    Copied from ScreenCapture Logic to use Qt image saving instead of VTK.
    Fixes a color problem when saving as jpg instead of PNG
    """
    slicer.app.processEvents()
    slicer.util.forceRenderAllViews()

    # Grab the main window and use only the viewport's area
    allViews = slicer.app.layoutManager().viewport()
    topLeft = allViews.mapTo(slicer.util.mainWindow(), allViews.rect.topLeft())
    bottomRight = allViews.mapTo(slicer.util.mainWindow(), allViews.rect.bottomRight())
    imageSize = bottomRight - topLeft

    if imageSize.x() < 2 or imageSize.y() < 2:
      # image is too small, most likely it is invalid
      raise ValueError('Capture image from view failed')

    img = ctk.ctkWidgetsUtils.grabWidget(slicer.util.mainWindow(),
                                         qt.QRect(topLeft.x(), topLeft.y(), imageSize.x(), imageSize.y()))

    img.save(filePath)

  def exportVolumeToDicom(self):
    """
    Export the current volume node as a DICOM
    A new patient and study is created (if doesn't exist) and
    the volume is put inside the study
    """

    # Create patient and study hierarchy if volume isn't already in a hierarchy
    self._createVolumeStudyHierarchyIfNeeded()

    exportDialog = slicer.qSlicerDICOMExportDialog()

    # Configure the output directory to be the default export directory.
    # (This method doesn't exist in Slicer master at the moment)
    if hasattr(exportDialog, 'setOutputDirectory'):
      exportDialog.setOutputDirectory(ExportDirectorySettings.load())
    exportDialog.setMRMLScene(slicer.mrmlScene)
    exportDialog.execDialog(self._volumeHierarchyId())

  def DVDexport(self):
    """
    Export the current volume node as a DICOM
    A new patient and study is created (if doesn't exist) and
    the volume is put inside the study
    """
    # w = qt.QDialog()
    # b1 = qt.QPushButton(w)
    # b1.setText("DICOM")
    # b1.move(30,50)
    # b2 = qt.QPushButton(w)
    # b2.setText("MRB data")
    # b2.move(150,50)
    # b1.clicked.connect(self.showDVD1)
    # b2.clicked.connect(self.showDVD2)
    # w.setWindowTitle("SelectDVDdata")
    # w.exec_()
    self.showDVD1()
    # dicomWriteCD
    # cliNode = slicer.cli.run(dicomWrite, None, cliparameters, wait_for_completion=True)
    # p = qt.QProcess()
    # p.start("./BurnCD.exe", ['str'])
  def showDVD1(self):
    path = os.getcwd()
    # p = qt.QProcess() 
    path = os.path.dirname(os.path.dirname(sys.executable))
    exepath = os.path.join(path, "BurnMedia.exe dicom")
    subprocess.Popen(exepath)
    # os.system(exepath)
    # msg = qt.QMessageBox()
    # msg.setText(exepath)
    # msg.exec_()
    # dicomPath = ExportDirectorySettings.load() + "/DICOM16"
    # exepath = exepath + " " + dicomPath
    # msg = qt.QMessageBox()
    # msg.setText(exepath)
    # msg.exec_()
    # tmp = exepath + " dicom " + dicomPath
    # print(exepath)
    # print(dicomPath)
    # subprocess.Popen(tmp)
    # os.system(tmp)
    # p.start("./BurnCD.exe", ['str'])
    # self.dicomWrite = slicer.modules.dvdexport.widgetRepresentation()
  def showDVD2(self):
    path = os.getcwd()
    # p = qt.QProcess() 
    path = os.path.dirname(os.path.dirname(sys.executable))
    exepath = os.path.join(path, "BurnMedia.exe mrb")
    # os.system(exepath)
    # msg = qt.QMessageBox()
    # msg.setText(exepath)
    # msg.exec_()
    # os.system(exepath)
    subprocess.Popen(exepath)
    # p.start("./BurnCD.exe", ['str'])
    # self.dicomWrite = slicer.modules.dvdexport.widgetRepresentation()
  def _createVolumeStudyHierarchyIfNeeded(self):
    """Put the volume under a Patient and Study if the volume is not already contained in a Study"""
    if self._isVolumeInStudyHierarchy():
      return

    volumeShItemID = self._volumeHierarchyId()
    self.patientItemID = self.hierarchyNode.CreateSubjectItem(
      self.hierarchyNode.GetSceneItemID(), self.tr('New patient')
    )
    self.studyItemID = self.hierarchyNode.CreateStudyItem(
      self.patientItemID, self.tr('New study')
    )

    self.hierarchyNode.SetItemParent(volumeShItemID, self.studyItemID)

  def _volumeHierarchyId(self):
    """Returns ID of the volume in the hierarchy node"""
    return self.hierarchyNode.GetItemByDataNode(self.volumeNode)

  def _isVolumeInStudyHierarchy(self):
    """Returns True if volume is already contained in a study. False otherwise"""
    return self.hierarchyNode.GetItemLevel(self.hierarchyNode.GetItemParent(self._volumeHierarchyId())) == "Study"

  def exportVolumeToRaw(self):
    """
    Export the current volume into non compressed .mhd file
    """
    self.exportVolume(RFExportVolumeType.RFExportRAW)

  def exportVolumeToTIFF(self):
    """
    Export the current volume into non compressed .tiff file
    """
    self.exportVolume(RFExportVolumeType.RFExportTIFF)

  @staticmethod
  def _exportPath(fileName):
    return os.path.join(ExportDirectorySettings.load(), fileName)

  def exportVolume(self, exportType):
    """
    Export the current volume into the correct extension
    The current supported file are :
      - mhd
      - tiff

    Parameters:
      exportType (RFExportVolumeType): Define the extension
    """

    if exportType == RFExportVolumeType.RFExportRAW:
      outputVolumeName = 'Volume.mhd'
      fileFilter = self.tr('File (*.mhd)')
      fileExtension = '.mhd'
    elif exportType == RFExportVolumeType.RFExportTIFF:
      outputVolumeName = 'Volume.TIFF'
      fileFilter = self.tr('File (*.TIFF)')
      fileExtension = '.TIFF'
    else:
      return

    path = qt.QFileDialog.getSaveFileName(None, self.tr('Save File'), self._exportPath(outputVolumeName), fileFilter)

    if not path:
      return

    IOManager = slicer.app.coreIOManager()
    volumeNode = slicer.modules.RFViewerHomeWidget.getDataLoader().getCurrentVolumeNode()
    fileType = IOManager.fileWriterFileType(volumeNode)

    savingParameters = {
      'nodeID': volumeNode.GetID(),
      'fileName': self._tmpSymLink.getSymlinkToNewPath(path),
      'fileFormat': fileExtension,
      'useCompression': 0
    }

    success = IOManager.saveNodes(fileType, savingParameters)

    if success:
      warningMessageBox(self.tr('Export'), self.tr('Export succeeded'))
    else:
      warningMessageBox(self.tr('Export'), self.tr('Export failed'))

  def exportSegmentToSTL(self):
    """
    Export the current segmentation node as an stl file
    """
    destinationFolder = qt.QFileDialog.getExistingDirectory(None, self.tr('Choose segment directory'),
                                                            ExportDirectorySettings.load())

    if not destinationFolder:
      return

    segmentationNode = slicer.modules.RFSegmentationWidget.getSegmentationNode()

    if segmentationNode is None:
      return

    displayNode = slicer.modules.RFSegmentationWidget.getDisplaySegmentationNode()
    visibleSegmentIds = vtk.vtkStringArray()
    displayNode.GetVisibleSegmentIDs(visibleSegmentIds)

    segmentLogic = slicer.modules.segmentations.logic()
    saved = segmentLogic.ExportSegmentsClosedSurfaceRepresentationToFiles(
      self._tmpSymLink.getSymlinkToExistingPath(destinationFolder),
      segmentationNode,
      visibleSegmentIds
    )

    if saved:
      warningMessageBox(self.tr('Segment export'), self.tr('Export succeeded'))
    else:
      warningMessageBox(self.tr('Segment export'), self.tr('Export failed'))

  def onSessionLoaded(self):
    """When session is loaded get current volume node and get scene hierarchy node"""
    self.volumeNode = self._dataLoaderWidget.getCurrentVolumeNode()
    self.hierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
