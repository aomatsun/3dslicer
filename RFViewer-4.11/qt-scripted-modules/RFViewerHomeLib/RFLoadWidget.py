import os
import re

import qt
import slicer
import vtk

from RFViewerHomeLib import Signal, removeNodeFromMRMLScene, wrapInQTimer, translatable, strToBool, warningMessageBox, \
    nodeID, ExportDirectorySettings, listEveryFileInDirectory


@translatable
class DataLoader(object):
    """
    Object responsible for loading a DICOM and notifying listeners on DICOM Load
    """

    def __init__(self):
        self._importButton = None
        self._newNodeObserver = None
        self._currentVolumeNode = None
        self._ignoredVolumeNames = set()
        self._isNewVolumeSettingEnabled = True
        self._isVolumeAddedNotificationEnabled = True
        self._previousLoadedDataDir = ""

        self.volumeNodeChanged = Signal("vtkMRMLVolumeNode")

        # Connect slicer node added event to newNodeAdded notification
        self._addNewNodeObserver()

        # Connect window drop event to data loading (only available in RFViewerApp and not Slicer)
        try:
            slicer.util.mainWindow().onDropEvent.connect(self.onDropEvent)
        except AttributeError:
            pass

    @staticmethod
    def _removeNameIndexSuffix(name):
        """
        Remove name index pattern added by Slicer when creating new node in the scene.

        Example:
           _removeNameIndex("Name_suffix") -> "Name_suffix"
           _removeNameIndex("Name_3345_01") -> "Name_3345"
           _removeNameIndex("Name") -> "Name"

        :param name: str - Name to sanitize
        :return: str - Name with index suffix removed. Empty string if Name is None or empty.
        """
        if not name:
            return ""

        match = re.search(r"^(.*?)(_\d+\Z)", name)
        return match.group(1) if match else name

    def __del__(self):
        self._removeNewNodeObserver()

    def addIgnoredVolumeName(self, volumeName):
        """
        When a vtkMRMLVolumeNode is added to the scene, if the name of the volume is ignored, the previous volume node
        will not be removed and the node listeners will not be notified of this node.

        :param volumeName: str - Name of the node to ignore
        """
        self._ignoredVolumeNames.add(self._removeNameIndexSuffix(volumeName))

    def _removeCurrentVolumeNode(self):
        if self._currentVolumeNode is not None:
            # Remove volume node from scene
            removeNodeFromMRMLScene(self._currentVolumeNode)
            # Remove volume ROI node from scene
            self._removeAllAnnotationFromSceneROI()

    @staticmethod
    def _removeAllAnnotationFromSceneROI():
        """Remove all previous annotation ROI from scene as removing volumes does not remove the associated ROI"""
        for roi in slicer.util.getNodesByClass("vtkMRMLAnnotationROINode"):
            removeNodeFromMRMLScene(roi)

    def getCurrentNodeID(self):
        return nodeID(self._currentVolumeNode)

    def getCurrentVolumeNode(self):
        return self._currentVolumeNode

    def setCurrentVolumeNode(self, newNode):
        """
        Set current volume node to new node and notify the different listeners of node change.

        If the new node is None, the old node will be removed from the mrmlScene and the listeners will be notified of
        None new node.
        """
        if self._currentVolumeNode != newNode:
            self._removeCurrentVolumeNode()
            self._currentVolumeNode = newNode
            self._notifyNewVolumeAdded()

    def _addNewNodeObserver(self):
        if self._newNodeObserver is not None:
            self._removeNewNodeObserver()

        self._newNodeObserver = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeAboutToBeAddedEvent,
                                                             self._onSlicerNodeAdded)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onSlicerNodeAdded(self, caller, event, newNode):
        # Ignore new nodes in ignored volume names
        # Take pattern of the name without name index suffixes to handle the case where the name of the node to ignore
        # is NodeNamePattern but the node is instantiated as NodeNamePattern_1
        isIgnored = self._removeNameIndexSuffix(newNode.GetName()) in self._ignoredVolumeNames
        if isIgnored or not isinstance(newNode, slicer.vtkMRMLVolumeNode):
            return

        self._onNewVolumeAdded(newNode)

    def _onNewVolumeAdded(self, newNode):
        if newNode is not None and self._isNewVolumeSettingEnabled:
            self.setCurrentVolumeNode(newNode)

    def _removeNewNodeObserver(self):
        if self._newNodeObserver is not None:
            slicer.mrmlScene.RemoveObserver(self._newNodeObserver)
            self._newNodeObserver = None

    @wrapInQTimer
    def _notifyNewVolumeAdded(self):
        if self._currentVolumeNode is not None:
            self._currentVolumeNode.SetUndoEnabled(True)

        if self._isVolumeAddedNotificationEnabled:
            self.volumeNodeChanged.emit(self._currentVolumeNode)

    @wrapInQTimer
    def onLoadDICOMClicked(self):
        """Show DICOM Widget as popup
        """
        dicomWidget = self._getDicomWidget()

        if dicomWidget is not None:
            try:
                dicomWidget.detailsPopup.open()
            except AttributeError:  # Dicom widget changed in version 4.11
                # Override DICOM warning frame style sheet (frame doesn't exist prior to Slicer 4.10)
                slicer.util.findChild(dicomWidget.browserWidget, "DatabaseDirectoryProblemFrame").setStyleSheet(
                    "background-color:#0099CC")

                # Hide advanced button
                slicer.util.findChild(dicomWidget.browserWidget, "AdvancedViewCheckBox").setVisible(False)

                # Show dicom widget as a popup
                dicomWidget.browserWidget.setWindowFlags(qt.Qt.Popup | qt.Qt.Dialog)

                # Add import button to layout
                if self._importButton is None:
                    self._importButton = qt.QPushButton(self.tr("Import DICOM Files"))
                    self._importButton.clicked.connect(self.onImportDICOMClicked)

                    actionFrame = slicer.util.findChild(dicomWidget.browserWidget, "ActionButtonsFrame")
                    actionFrame.layout().insertWidget(2, self._importButton)

                    # Add translation for the load button
                    loadButton = slicer.util.findChildren(actionFrame, text="Load")[0]
                    loadButton.setText(self.tr("Load"))
                    loadButton.setToolTip(self.tr("Load selected item into the scene"))

                if strToBool(qt.QSettings().value("windowAlwaysOnTop")):
                    dicomWidget.browserWidget.setWindowFlag(qt.Qt.WindowStaysOnTopHint, True)

                dicomWidget.browserWidget.show()
                self._centerWidget(dicomWidget.browserWidget, slicer.util.mainWindow())

    @staticmethod
    def _getDicomWidget():
        try:
            dicomWidget = slicer.modules.DICOMWidget
        except AttributeError:
            dicomWidget = slicer.modules.dicom.widgetRepresentation().self()
        return dicomWidget

    @staticmethod
    def _centerWidget(widget, host):
        widget.move(host.geometry.center() - widget.rect.center())

    def onLoadDataClicked(self):
        """
        Load volumes files from the following types : (*.mha *.mhd *.nrrd *.tiff)

        Only single file import is supported at the moment
        """
        # Query file to load from user
        filePath = qt.QFileDialog.getOpenFileName(None, self.tr("Import volume file"), self._previousLoadedDataDir,
                                                  self.tr("Volume File") + " (*.mha *.mhd *.nrrd *.tiff)")

        if not filePath:
            return

        self.loadData(filePath)

    def onImportDICOMClicked(self):
        """
        Import every .dcm file in given input directory
        """
        dicomWidget = self._getDicomWidget()
        dirPath = qt.QFileDialog.getExistingDirectory(dicomWidget.browserWidget,
                                                      self.tr("Import DICOM Files from directory ..."),
                                                      self._previousLoadedDataDir)

        if not dirPath:
            return

        dicomFiles = listEveryFileInDirectory(dirPath, fileExt=".dcm")
        dicomWidget.browserWidget.dicomBrowser.importFiles(dicomFiles)

    def loadData(self, filePath):
        # Disable setting new volume on new node added to make sure the file loading is correctly finished first
        # If notification is done too early, the volume rendering display node will not be created correctly
        node = None
        prevIsNewVolumeSettingEnabled = self._isNewVolumeSettingEnabled
        self._isNewVolumeSettingEnabled = False

        # Import volume node from file
        try:
            node = slicer.util.loadNodeFromFile(filePath, "VolumeFile")
            self._previousLoadedDataDir = os.path.dirname(filePath)
        except RuntimeError:
            warningMessageBox(self.tr("Failed to import volume"), self.tr('Failed to import volume file : ') + filePath)

        # Re enable setting new volume
        self._isNewVolumeSettingEnabled = prevIsNewVolumeSettingEnabled

        # Notify new node added if correctly set
        self._onNewVolumeAdded(node)

        # Save file path as default export path
        ExportDirectorySettings.save(filePath)
        
       
        return node
    # def makeInt(self, s):
    #     if type(s) == "string":
    #         s = s.strip()

    #     return int(s) if s else 0
    # def onLoadDataofMnri(self, filePath):
    #     msg = qt.QMessageBox()
    #     msg.setText(filePath)
    #     msg.exec_()
    #     if not filePath:
    #         return
    #     filePath = os.path.join(os.path.dirname(filePath), "NAOMICT.mnri")
    #     IndustryTypeValue = qt.QSettings().value("IndustryType")
    #     try:
    #         mnri_settings = RFReconstructionLogic.MNRISettings(filePath)
    #         volx = self.makeInt(mnri_settings.value("BackProjection/VolXDim"))
    #         if volx > 0 :
    #             qt.QSettings().setValue("volx", volx)
    #         patientId = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientId"))
    #         patientName = mnri_settings.value("DicomPatientInfo/PatientName")
            
    #         patientSex = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientSex"))
    #         if patientSex == 1:
    #             patientSexStr = "Male"
    #         elif patientSex == -1:
    #             patientSexStr = "Female"
    #         else:
    #             patientSexStr = "Unknown"
    #         y = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthYear"))
    #         m = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthMonth"))
    #         d = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthDate"))
    #         if y > 0 and m > 0 and d > 0: 
    #             BithdayDate = qt.QDate(y , m , d).toString("yyyy.MM.dd")
    #         else: 
    #             BithdayDate = "2000.1.1"
    #         datetime = qt.QDate.currentDate()
    #         strnow = datetime.toString(qt.Qt.ISODate)
    #         strnow = strnow.replace("-",".")
    #         tmpstr = str(patientId) + " /" + patientName + " /" + patientSexStr + " /" +BithdayDate + " /" +strnow
    #         if IndustryTypeValue == "Industrial":      
    #             qt.QSettings().setValue("patientInfo", str(patientId) + " /" + strnow)
    #         else:
    #             qt.QSettings().setValue("patientInfo", tmpstr)
    #     except:
    #         qt.QSettings().setValue("patientInfo", "")
    # 
    def onDropEvent(self, event):
        """On drop event, try to load Data as Volume"""
        urls = event.mimeData().urls()
        if len(urls) == 1:
            self.loadData(urls[0].toLocalFile())
            event.acceptProposedAction()

    def setNewVolumeSettingEnabled(self, isEnabled):
        """Enable or disable setting new volume node added to MRML scene as the current volume node of RFViewer"""
        self._isNewVolumeSettingEnabled = isEnabled

    def setVolumeAddedNotificationEnabled(self, isEnabled):
        """Enable or disable notification of the new volume listeners of a newly added volume"""
        self._isVolumeAddedNotificationEnabled = isEnabled

    def restoreCurrentNodeFromID(self, nodeId):
        self._currentVolumeNode = slicer.mrmlScene.GetNodeByID(nodeId)
