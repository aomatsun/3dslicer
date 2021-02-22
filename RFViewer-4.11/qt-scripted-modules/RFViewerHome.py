import logging
import codecs
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from RFViewerHomeLib import *
from RFReconstruction import *
from RFReconstruction import RFReconstructionLogic
from RFViewerHomeLib import DataLoader, ModuleWidget, ToolbarWidget, createButton, Icons, \
    translatable, ProgressBar, RFSessionSerialization, ExportDirectorySettings , RFViewerWidget, warningMessageBox, wrapInCollapsibleButton
import ScreenCapture
import pydicom
# from oct2py import Oct2Py
import threading
from skimage.transform import iradon, radon
from datetime import datetime

class RFViewerHome(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RF Viewer Home"
        self.parent.categories = ["RFCo"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


@translatable
class RFViewerHomeWidget(RFViewerWidget):
    """
    Widget responsible for instantiating, displaying the different modules and displaying a toolbar for module access
    """

    def __init__(self, parent=None):
        RFViewerWidget.__init__(self, parent)
        self._dataLoaderWidget = None
        self._sessionSerializer = None
        self._toolbarLayout = None
        self._moduleWidget = None
        self._toolbarWidget = None
        self._patientInfoWidget = None
        self._previousModule = None
        self._visualizationWidget = None
        self._reconstructionWidget = None
        self._panoramaReconstructionWidget = None
        self._annotationWidget = None
        self._panoramaWidget = None
        self._segmentationWidget = None
        self._implantWidget = None
        self._exportWidget = None
        self._progressBars = {}
        self._currentWidget = None
        self._moduleWidget1 = None
        self.tmpstr = None
    def getDataLoader(self):
        return self._dataLoaderWidget

    @classmethod
    def _initDefaultSettings(cls):
        # Set GPU raycasting as default rendering mode
        qt.QSettings().setValue("VolumeRendering/RenderingMethod", "vtkMRMLGPURayCastVolumeRenderingDisplayNode")

        # Disable exit dialog
        qt.QSettings().setValue("MainWindow/DisableExitDialog", True)

        # Enable internationalization
        qt.QSettings().setValue("Internationalization/Enabled", True)

        # Set default values if they don't exist
        cls._setDefaultIfDoesntExist("IndustryType", "Medical")
        cls._setDefaultIfDoesntExist("Internationalization/Language", "ja_JP")

        if qt.QSettings().value("VolumeRendering/GPUMemorySize", "") == "":
            slicer.util.findChild(slicer.app.settingsDialog(), "GPUMemoryComboBox").setCurrentText("6 GB")

    @classmethod
    def _setDefaultIfDoesntExist(cls, key, value):
        if qt.QSettings().value(key, "") == "":
            qt.QSettings().setValue(key, value)

    @staticmethod
    def _initPythonConsoleColors():
        """"Change python prompt colors to be compatible with dark color scheme"""
        lightColor = qt.QColor("#ffb86c")  # orange

        pythonColorMap = {"PromptColorPicker": lightColor,  #
                          "CommandTextColorPicker": lightColor,  #
                          "WelcomeTextColorPicker": lightColor,  #
                          "BackgroundColorPicker": qt.QColor("#19232d"),  # dark blue
                          "OutputTextColorPicker": qt.QColor("#50fa7b"),  # green
                          "ErrorTextColorPicker": qt.QColor("#ff5555"),  # red
                          }

        settingsDialog = slicer.app.settingsDialog()
        for pickerName, color in pythonColorMap.items():
            try:
                picker = slicer.util.findChild(settingsDialog, pickerName)
                picker.colorChanged(color)

            except RuntimeError:
                logging.error("Failed to set python console color {}".format(pickerName))

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        # Initialize settings
        self._initDefaultSettings()
        self._initPythonConsoleColors()

        # Instantiate module widgets
        self._instantiateModuleWidgets()

        # Instantiate data loader and connect data loading and widget progress reporting
        self._dataLoaderWidget = DataLoader()
        self._connectDataLoading()
        self._connectWidgetProgressReporting()

        # Instantiate session serialization object
        self._sessionSerializer = RFSessionSerialization(rfWidgets=self._rfModuleWidgets(), loadWidget=self._dataLoaderWidget)

        # Instantiate Toolbar and module widgets
        self._toolbarWidget = ToolbarWidget()
        self._patientInfoWidget = qt.QLabel()
        self._showhidebutton = qt.QPushButton("show/hide Panel")
        self._showhidebutton.adjustSize()
        self._moduleWidget = ModuleWidget()
        self._moduleWidget1 = ModuleWidget() 
        # Add toolbar button to the top of the dock to always be visible even on module change
        # When loading RFViewerHome inside of Slicer, toolbar will be displayed under the Slicer logo
        self.toolbarButton = wrapInCollapsibleButton(self._toolbarWidget, collapsibleText=self.tr("Toolbar"),
                                                isCollapsed=False)
        self.ModulePanel = slicer.util.findChild(slicer.util.mainWindow(), "ModulePanel")
        self.dock_content = slicer.util.findChild(slicer.util.mainWindow(), "dockWidgetContents")
        self._patientInfoWidget.setText("")
        # self._patientInfoWidget.setStyleSheet("QLabel { color : orange; }")
        # self.dock_content.layout().insertWidget(1, self._showhidebutton, 1, 4)
        self.dock_content.layout().insertWidget(1, self._patientInfoWidget)
        self.dock_content.layout().insertWidget(2, self.toolbarButton)
        
        # self._showhidebutton.clicked.connect(self.showhidePanel)

        # Add the module widget to the module layout
        self.layout.addWidget(self._moduleWidget1)
        self.layout.addWidget(self._moduleWidget)
    
        # Configure toolbar sections
        self._configureToolbarFileSection()
        self._configureToolbarReconstructionSection()
        self._configureToolbarAnnotationSection()
        if qt.QSettings().value("IndustryType") == "Medical": 
            self._configureToolbarSegmentationSection()
        else:
            self._configureToolbarPanoramaSection()   
    # self._configureToolbarExportSection()
    #    self._configureUndoSection()

        # Close toolbar section and add stretch
        self._toolbarWidget.closeLastSection()
    #    self.layout.addStretch()

        # Load visualisation module by default
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization")) 

        # Load MRB files if any.
        main_window = slicer.util.mainWindow()
        if hasattr(main_window, "commandLineParsed"):
            main_window.commandLineParsed.connect(self._loadCommandLineFiles)
        main_window.onDropEvent.connect(self.onDropEvent)
        # self.dock_content.setFixedWidth(400)
    def onDropEvent(self, event):
        """On drop event, try to load Data as Volume"""
        urls = event.mimeData().urls()
        if len(urls) == 1:
            self.onLoadData(urls[0].toLocalFile())
            tmpfilepath = urls[0].toLocalFile()
            print ("tmpfilepath")
            if tmpfilepath.endswith(".mrb"):
                self._sessionSerializer.loadSession(tmpfilepath)
                ExportDirectorySettings.save(tmpfilepath)
            event.acceptProposedAction()

    def makeInt(self, s):
        if type(s) == "string":
            s = s.strip()

        return int(s) if s else 0
    def showhidePanel(self):
        dirPath = ExportDirectorySettings.load()
        if dirPath is None:
            return
        threads = []
        for j in range(20): 
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            for i in range(20):
                filename = ""
                dcmfile_index = i + j * 20
                if dcmfile_index < 10:
                    filename = "IMG000" + str(dcmfile_index)
                elif  dcmfile_index < 100:
                    filename = "IMG00" + str(dcmfile_index)
                elif  dcmfile_index < 1000:
                    filename = "IMG0" + str(dcmfile_index)
                elif  dcmfile_index < 10000:
                    filename = "IMG" + str(dcmfile_index)
                filename = filename + ".dcm"
                t = threading.Thread(target=self.print_time , args=(filename,))
                threads.append(t)
                t.start()
            print("All threads are started")

            for t1 in threads:
                t1.join() # Wait until thread terminates its task
            print("All threads completed")

    def print_time(self, dicomfilename):
        filename = ExportDirectorySettings.load() + "/DICOM16/" + dicomfilename
        dicomDirPath = ExportDirectorySettings.load()  + "/DICOM_tmp"
        if os.path.isdir(dicomDirPath) != True:
            os.mkdir(dicomDirPath)
        ds = pydicom.dcmread(filename)
        image = ds.pixel_array
        image[( ds.pixel_array < 0)] = 0
        theta = np.linspace(0., 180., max(image.shape), endpoint=False)
        sinogram = radon(image, theta=theta, circle=True)
        tmp = sinogram
        maxvalue = np.max(sinogram)
        print("maxvalue")
        print(maxvalue)
        if maxvalue < 19:
            ds.save_as(dicomDirPath + "/"+ dicomfilename)
            return
        average = self.Average(self.Average(tmp))
        threshold = (np.max(sinogram) - average) / 10
        
        tmp[ (tmp > (threshold * 7.3 + average)) ] = threshold * 7.3 + average
        reconstruction_fbp = iradon(tmp, theta=theta, circle=True)
        ds.PixelData  = reconstruction_fbp
        ds.save_as(dicomDirPath + "/"+ dicomfilename)
        return

    def Average(self, lst): 
        return sum(lst) / len(lst) 
    def _loadCommandLineFiles(self):
        """
        Load first MRB file in passed command line files if any.
        """
        # getCommandLineFiles method is not available in Slicer
        main_window = slicer.util.mainWindow()
        if not hasattr(main_window, "getCommandLineFiles"):
            return
        
        files = main_window.getCommandLineFiles()
        for file in files:
            print(file)
            if file.endswith(".mrb"):
                self._sessionSerializer.loadSession(file)
            if file.endswith(".mrb") or file.endswith(".mhd"):
                self.onLoadData(file)
                return

    def _instantiateModuleWidgets(self):
        self._visualizationWidget = slicer.util.getModuleGui(slicer.modules.rfvisualization)
        self._reconstructionWidget = slicer.util.getModuleGui(slicer.modules.rfreconstruction)
        self._panoramaReconstructionWidget = slicer.util.getModuleGui(slicer.modules.rfpanoramareconstruction)
        self._annotationWidget = slicer.util.getModuleGui(slicer.modules.rfannotation)
        self._implantWidget = slicer.util.getModuleGui(slicer.modules.rfimplant)
        self._panoramaWidget = slicer.util.getModuleGui(slicer.modules.rfpanorama)
        self._segmentationWidget = slicer.util.getModuleGui(slicer.modules.rfsegmentation)
        self._exportWidget = slicer.util.getModuleGui(slicer.modules.rfexport)

    def _rfModuleWidgets(self):
        """
        List of all the RFViewerWidgets of the application.
        The widgets are different from the slicer.modules UI which are instances of qSlicerScriptedLoadableModuleWidget.
        """
        return [self,  #
                slicer.modules.RFVisualizationWidget,  #
                slicer.modules.RFReconstructionWidget,  #
                slicer.modules.RFAnnotationWidget,  #
                slicer.modules.RFImplantWidget,  #
                slicer.modules.RFPanoramaWidget,  #
                slicer.modules.RFPanoramaReconstructionWidget,  #
                slicer.modules.RFSegmentationWidget,  #
                slicer.modules.RFExportWidget]

    def _connectDataLoading(self):
        for moduleWidget in self._rfModuleWidgets():
            self._dataLoaderWidget.volumeNodeChanged.connect(moduleWidget.setVolumeNode)

    def _connectWidgetProgressReporting(self):
        for moduleWidget in self._rfModuleWidgets():
            self.connectProgressSignal(moduleWidget)
            moduleWidget.setLoadWidget(self._dataLoaderWidget)
    def onLoadData(self, filePath):
        if not filePath:
            return
        filePath = os.path.join(os.path.dirname(filePath), "NAOMICT_UTF8.mnri")
        IndustryTypeValue = qt.QSettings().value("IndustryType")
        self._patientInfoWidget.setText("")
        try:    
            mnri_settings = RFReconstructionLogic.MNRISettings(filePath)
            volx = self.makeInt(mnri_settings.value("BackProjection/VolXDim"))
            if volx > 0:
                qt.QSettings().setValue("volx", volx)
            patientId = mnri_settings.value("DicomPatientInfo/PatientId")
            
            patientName = mnri_settings.value("DicomPatientInfo/PatientName")
            patientSex = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientSex"))
            if patientSex == 1:
                patientSexStr = "Male"
            elif patientSex == -1:
                patientSexStr = "Female"
            else:
                patientSexStr = "Unknown"
            y = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthYear"))
            m = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthMonth"))
            d = self.makeInt(mnri_settings.value("DicomPatientInfo/PatientBirthDate"))
            if y > 0 and m > 0 and d > 0: 
                BithdayDate = qt.QDate(y , m , d).toString("yyyy.MM.dd")
            else: 
                BithdayDate = "2000.1.1"
            datetime = qt.QDate.currentDate()
            strnow = datetime.toString(qt.Qt.ISODate)
            strnow = strnow.replace("-",".")
            tmpstr = str(patientId) + " /" + patientName + " /" + patientSexStr + " /" +BithdayDate + " /" +strnow
            if IndustryTypeValue == "Industrial":      
                self._patientInfoWidget.setText(str(patientId) + " /" + strnow)
            else:
                self._patientInfoWidget.setText(tmpstr)
        except:
            self._patientInfoWidget.setText("")
    def _configureToolbarFileSection(self):
        self._toolbarWidget.createSection(self.tr("File"))
       # Save session
        reconstruction3dButton = createButton("", self.loadReconstructionModule)
        reconstruction3dButton.setIcon(Icons.reconstruction3d)
        self._toolbarWidget.addButton(reconstruction3dButton)
        
        sessionSaveButton = createButton("", lambda *x: self._sessionSerializer.onSaveSession())
        sessionSaveButton.setIcon(Icons.sessionSave)
        self._toolbarWidget.addButton(sessionSaveButton)
        
        exportDICOMButton = createButton("", self.loadExportModule)
        exportDICOMButton.setIcon(Icons.exportDICOM)
        self._toolbarWidget.addButton(exportDICOMButton)
        
        
        

    def _configureToolbarReconstructionSection(self):
        self._toolbarWidget.createSection()

        takeScreenshotButton = createButton("", self.loadTakeScreenshotModule)
        takeScreenshotButton.setIcon(Icons.takeScreenshot)
        self._toolbarWidget.addButton(takeScreenshotButton)

        DVDExportButton = createButton("", self.DVDexportModule)
        DVDExportButton.setIcon(Icons.DVDexport)
        self._toolbarWidget.addButton(DVDExportButton)

    def _configureToolbarAnnotationSection(self):
        self._toolbarWidget.createSection(self.tr("Measuring Instruments"))
        # self._toolbarWidget.addButton(createButton(self.tr("Measuring Instruments"), self.loadAnnotationModule))
        # self._toolbarWidget.addButton(
        #     createButton("", lambda *x: self.loadAnnotationModule, icon=Icons.measureTool), toolTip=self.tr("Measuring Instruments"))

        measureToolButton = createButton("", self.loadAnnotationModule)
        measureToolButton.setIcon(Icons.measureTool)
        self._toolbarWidget.addButton(measureToolButton) 

        
        AnnotationAngleButton = createButton("", self.loadAnnotationAngleModule)
        AnnotationAngleButton.setIcon(Icons.AnnotationAngle)
        self._toolbarWidget.addButton(AnnotationAngleButton)
    def _configureToolbarPanoramaSection(self):
        self._toolbarWidget.createSection(self.tr("描画ツール"))
        
        implantToolButton = createButton("", self.loadImplantModule)
        implantToolButton.setIcon(Icons.implantTool)
        self._toolbarWidget.addButton(implantToolButton) 
       
        AnnotationLineButton = createButton("", self.loadAnnotationLineModule)
        AnnotationLineButton.setIcon(Icons.AnnotationLine)
        self._toolbarWidget.addButton(AnnotationLineButton)
    def _configureToolbarSegmentationSection(self):
        SegmentationButton = createButton("", self.loadSegmentationModule)
        SegmentationButton.setIcon(Icons.Segmentation)
        self._toolbarWidget.addButton(SegmentationButton)


    def _configureToolbarExportSection(self):
        self._toolbarWidget.createSection()
        self._toolbarWidget.addButton(createButton(self.tr("Export Tools"), self.loadExportModule))

    def _configureUndoSection(self):
        self._toolbarWidget.createSection()
        self._toolbarWidget.addButton(createButton(self.tr("Undo"), self.undo))


    def loadAnnotationLineModule(self):
        self._currentWidget = slicer.modules.RFAnnotationWidget
        self._moduleWidget.setModule(self._annotationWidget, self.tr("Annotations"))
        self._currentWidget.onModuleOpened()
        self._currentWidget.canalWidget.addCanalButton.click()
    
    def loadAnnotationAngleModule(self):
        self._currentWidget = slicer.modules.RFAnnotationWidget
        self._moduleWidget.setModule(self._annotationWidget, self.tr("Annotations"))
        self._currentWidget.onModuleOpened()
        self._currentWidget._widget.createAnglePushButton.click()


    def connectProgressSignal(self, widget):
        widget.addProgressBar.connect(self.onAddProgressBar)
        widget.removeProgressBar.connect(self.onRemoveProgressBar)

    def onAddProgressBar(self, progressName):
        if progressName in self._progressBars:
            return

        progressBar = ProgressBar(progressName)
        self._progressBars[progressName] = progressBar
        self.layout.addWidget(progressBar)

    def loadSegmentationModule(self):
        self._currentWidget = slicer.modules.RFSegmentationWidget
        self._moduleWidget.setModule(self._segmentationWidget, self.tr("Segmentation"))
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))
        
    def onRemoveProgressBar(self, progressName):
        if progressName not in self._progressBars:
            return

        progressBar = self._progressBars[progressName]
        self.layout.removeWidget(progressBar)
        progressBar.setVisible(False)
        del self._progressBars[progressName]
    def loadTakeScreenshotModule(self):
        self._currentWidget = slicer.modules.RFExportWidget
        self._currentWidget.onModuleOpened()
        self._currentWidget.takeScreenshotButton.click()
    
    def DVDexportModule(self):
        self._currentWidget = slicer.modules.RFExportWidget
        self._currentWidget.onModuleOpened()
        self._currentWidget.DVDexportButton.click()
    
   
    def loadVisualisationModule(self):
        self._currentWidget = slicer.modules.RFVisualizationWidget
        self._moduleWidget.setModule(self._visualizationWidget, self.tr("Visualization"))
        self._currentWidget.onModuleOpened()

    def loadReconstructionModule(self):
        self._currentWidget = slicer.modules.RFReconstructionWidget
        self._moduleWidget.setModule(self._reconstructionWidget, self.tr("Reconstruction"))
        slicer.modules.RFReconstructionWidget.setLoadWidget(self._dataLoaderWidget)
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))

    def loadPanoramaReconstructionModule(self):
        self._moduleWidget.setModule(self._panoramaReconstructionWidget, self.tr("Panorama Reconstruction"))
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))
    def loadAnnotationModule(self):
        self._currentWidget = slicer.modules.RFAnnotationWidget
        self._moduleWidget.setModule(self._annotationWidget, self.tr("Annotations"))
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))
        self._currentWidget._widget.createLinePushButton.click()

    def loadImplantModule(self):
        self._currentWidget = slicer.modules.RFImplantWidget
        self._moduleWidget.setModule(self._implantWidget, self.tr("Implants"))
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization")) 
    def loadPanoramaModule(self):
        self._currentWidget = slicer.modules.RFPanoramaWidget
        self._moduleWidget.setModule(self._panoramaWidget, self.tr("Panorama"))
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))
    def loadSegmentationModule(self):
        self._currentWidget = slicer.modules.RFSegmentationWidget
        self._moduleWidget.setModule(self._segmentationWidget, self.tr("Segmentation"))
        self._currentWidget.onModuleOpened()
        self._moduleWidget1.setModule(self._visualizationWidget, self.tr("Visualization"))
    def loadExportModule(self):
        self._currentWidget = slicer.modules.RFExportWidget
        self._currentWidget.onModuleOpened()
        self._currentWidget.exportDicomButton.click()

    def undo(self):
        if self._currentWidget:
            self._currentWidget.undo()

    def onSessionAboutToBeSaved(self):
        parameterNode = self.getParameterNode()
        parameterNode.SetParameter("CurrentNodeID", self._dataLoaderWidget.getCurrentNodeID())

    def onSessionLoaded(self):
        parameterNode = self.getParameterNode()
        self._dataLoaderWidget.restoreCurrentNodeFromID(parameterNode.GetParameter("CurrentNodeID"))

    def reconstructAndSaveSession(self, mnriPath, mrbOutputPath):
        # Disable loading notifications
        self._dataLoaderWidget.setVolumeAddedNotificationEnabled(False)
        # Reconstruct synchronously
        mnri_settings = RFReconstructionLogic.MNRISettings(mnriPath)
        try: 
            typeValue = int(mnri_settings.value("Frame/Type"))
            if typeValue != 1:
                cli_node = slicer.modules.RFReconstructionWidget.reconstruct(mnriPath=mnriPath, isCliSynchronous=True)
            else:
                cli_node = slicer.modules.RFReconstructionWidget.reconstructForTwoImages(mnriPath)
        except:
            cli_node = slicer.modules.RFReconstructionWidget.reconstruct(mnriPath=mnriPath, isCliSynchronous=True)

        # # Reconstruct synchronously
        # cli_node = slicer.modules.RFReconstructionWidget.reconstruct(mnriPath=mnriPath, isCliSynchronous=True)

        # Save session if reconstruction was successful
        if not cli_node.GetStatusString() == 'Completed':
            warningMessageBox(self.tr("Reconstruction Failed"), f"{cli_node.GetErrorText()}")
            self._dataLoaderWidget.setVolumeAddedNotificationEnabled(True)
            return

        # Set new volume for the different widgets
        for widget in self._rfModuleWidgets():
            widget.setVolumeNode(self._dataLoaderWidget.getCurrentVolumeNode())

        # Wait until all widgets are updated with reconstructed volume and save the session
        slicer.app.processEvents()

        # Save session
        self._sessionSerializer.saveSession(mrbOutputPath, showMessageBox=False)

        # Enable notifications
        self._dataLoaderWidget.setVolumeAddedNotificationEnabled(True)


class RFViewerHomeLogic(ScriptedLoadableModuleLogic):
    """Empty logic class for the module to avoid error report on module loading"""
    pass
