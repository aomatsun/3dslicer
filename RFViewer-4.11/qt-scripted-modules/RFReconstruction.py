import errno
import shutil
import logging
import os
import unittest
import sys
import numpy
import qt
import slicer
from sys import byteorder as system_endian
from array import array
import pickle
import numpy as np
from slicer.ScriptedLoadableModule import *
import chardet
import math
from RFViewerHomeLib import createButton, createFileSelector, translatable, RFViewerWidget, removeNodeFromMRMLScene, \
    TemporarySymlink, ExportDirectorySettings, DataLoader
import time
import re
import CropVolumeSequence
import cv2
import codecs

from skimage.transform import radon, rescale, iradon,iradon_sart
from skimage.data import shepp_logan_phantom
class RFReconstruction(ScriptedLoadableModule):
    """
    Module responsible for wrapping calls to volume reconstruction implemented as a Command Line Interface module
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)

        self.parent.title = "RF Reconstruction"
        self.parent.categories = ["RFCo"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


@translatable
class RFReconstructionWidget(RFViewerWidget):
    def __init__(self, parent):
        RFViewerWidget.__init__(self, parent)

        self._mnriLineEdit = None
        self._reconstructButton = None
        self._logic = RFReconstructionLogic()
        self._cliNode = None
        self._editCliWidget = None
        self._reconstructedVolume = None
        self._volumeFiltersUI = None
        self._volumeFiltersLogic = None
        self._dataLoaderWidget = None

        self._progressText = self.tr("Reconstructing...")

    def setup(self):
        RFViewerWidget.setup(self)

        # Disable module if CUDA is not found
        try:
            from RFReconstructionLib import RFVolumeFiltersUI, VolumeFiltersLogic
            self._volumeFiltersUI = RFVolumeFiltersUI()
            self._volumeFiltersUI.setEnabled(False)
            self._volumeFiltersLogic = VolumeFiltersLogic()
        except ImportError:
            noCUDALabel = qt.QLabel(self.tr('Please install CUDA to enable reconstruction.'))
            self.layout.addWidget(noCUDALabel)
            return

        self._mnriLineEdit = createFileSelector(self.updateReconstructButtonEnabled, [self.tr("MNRI File (*.mnri)")])
        self._reconstructButton = createButton(self.tr("開始"), self.onStartReconstruction)

        directoryFormLayout = qt.QFormLayout()
        directoryFormLayout.addRow(self.tr("MNRI File"), self._mnriLineEdit)
        self.layout.addLayout(directoryFormLayout)
        self.layout.addWidget(self._reconstructButton)
        self.layout.addWidget(self._volumeFiltersUI)
        self.layout.addStretch()

        # TODO: VolumeFilters should be stand-alone: takes a volume as input.
        self._volumeFiltersUI.medianButton.connect("clicked()", lambda *x: self.launchVolumeFilter(VolumeFiltersLogic.Type.Median))
        self._volumeFiltersUI.gaussianButton.connect("clicked()", lambda *x: self.launchVolumeFilter(VolumeFiltersLogic.Type.Gaussian))
        self._volumeFiltersUI.sharpenButton.connect("clicked()", lambda *x: self.launchVolumeFilter(VolumeFiltersLogic.Type.Sharpen))

        advancedSection = self.addAdvancedSection()
        advancedLayout = qt.QFormLayout(advancedSection)
        self._editCliWidget = slicer.util.getModuleGui(slicer.modules.simplertk)
        advancedLayout.addWidget(self._editCliWidget)

        self.layout.addStretch()

        self.updateReconstructButtonEnabled()

    def updateReconstructButtonEnabled(self):
        """
        Enable reconstruction when the MNRI file path is correctly set and update the CLI edition in the advanced
        section.
        """
        isEnabled = os.path.isfile(self._mnriLineEdit.currentPath) and (
                    self._cliNode is None or not self._cliNode.IsBusy())
        self._reconstructButton.setEnabled(isEnabled)

        self._editCliWidget.setEnabled(self._cliNode is not None)
        if self._cliNode is not None:
            self._editCliWidget.setEditedNode(self._cliNode)

    def launchVolumeFilter(self, filterType):
        if self._reconstructedVolume is None:
            return

        self._volumeFiltersUI.setEnabled(False)
        if filterType == self._volumeFiltersLogic.Type.Median:
            kernelSize = self._volumeFiltersUI.medianSlider.value
            self._volumeFiltersLogic.applyMedianFilter(self._reconstructedVolume, kernelSize)
        elif filterType == self._volumeFiltersLogic.Type.Gaussian:
            variance = self._volumeFiltersUI.gaussianSlider.value
            self._volumeFiltersLogic.applyGaussianFilter(self._reconstructedVolume, variance)
        elif filterType == self._volumeFiltersLogic.Type.Sharpen:
            self._volumeFiltersLogic.applySharpenFilter(self._reconstructedVolume)
        self._volumeFiltersUI.setEnabled(True)
    def onStartReconstruction(self, imgPath):
        mnri_settings = self._logic.MNRISettings(self._mnriLineEdit.currentPath)
        try: 
            typeValue = mnri_settings.value("Frame/Type")
            convertMar = float(mnri_settings.value("Frame/Mar"))
            print(convertMar)
            if convertMar == 1.0:
                self._logic.converting_mar_files(self._mnriLineEdit.currentPath)
            if typeValue != "":
                if int(typeValue) != 1:
                    self.reconstruct(isCliSynchronous=False, mnriPath=self._mnriLineEdit.currentPath)
                else:
                    mnrifilepath = self._mnriLineEdit.currentPath
                    self.reconstructForTwoImages(mnrifilepath)
            else:
                self.reconstruct(isCliSynchronous=False, mnriPath=self._mnriLineEdit.currentPath)    
        except:
            self.reconstruct(isCliSynchronous=False, mnriPath=self._mnriLineEdit.currentPath)
            # self.launchVolumeFilter1()
    def reconstructForTwoImages(self, mnrifilepath):
        self._logic.converting_files(mnrifilepath)
        
        self._dir_path = os.path.dirname(mnrifilepath)
        
        self.oddMnriPath = os.path.join(self._dir_path, "frame1/NAOMICT_UTF8.mnri") 
        self.evenMnriPath = os.path.join(self._dir_path, "frame2/NAOMICT_UTF8.mnri") 
        cliNode = self.reconstruct_odd(isCliSynchronous=True, mnriPath = self.oddMnriPath )
        shutil.rmtree(os.path.join(self._dir_path, "frame1"))
        shutil.rmtree(os.path.join(self._dir_path, "frame2"))
        shutil.rmtree(os.path.join(self._dir_path, "frame_result1"))
        shutil.rmtree(os.path.join(self._dir_path, "frame_result2"))
        # tmp = CropVolumeSequence.CropVolumeSequenceWidget()
        # tmp.onApplyButton()
        return cliNode
    def reconstruct(self, mnriPath, isCliSynchronous):
        # Mar
        mnri_settings = self._logic.MNRISettings(mnriPath)
        # typevalues = mnri_settings.value("Frame/Type")
        # if typevalues == 1:
        dir_path = os.path.dirname(mnriPath)
        filecount = int(mnri_settings.value("Frame/FrameCount"))
        print(filecount)

        # for i in range(1, 2, 1):
        #     if i < 10:
        #         img_path = "image_00" + str(i) + ".img"
        #     elif i< 100:
        #         img_path = "image_0" + str(i) + ".img"
        #     else:
        #         img_path = "image_" + str(i) + ".img"
        #     img_file_path = os.path.join(dir_path, "frame/" + img_path)
        #     print(img_file_path)
            
        #     tmp_result = np.fromfile(img_file_path, dtype=np.uint16) 
        #     image = tmp_result.reshape(616, int(len(tmp_result) / 616))
            
            
            
        #     image = rescale(image, scale=0.4, mode='reflect', multichannel=False)

        #     theta = np.linspace(0., 180., max(image.shape), endpoint=False)
        #     # imagedata = rescale(imagedata, scale=0.4, mode='reflect', multichannel=False)
        #     sinogram = radon(image, theta=theta,circle=False)
        #     print("sinogram")
        #     print(sinogram)
        #     reconstruction_fbp = iradon(sinogram, theta=theta,circle=False)
        #     reconstruction_sart = iradon_sart(sinogram, theta=theta)
        #     reconstruction_sart2 = iradon_sart(sinogram, theta=theta,
        #                             image=reconstruction_sart)
        #     print(reconstruction_sart2)
        # Synchronize line edit file path with input file path if necessary
        if self._mnriLineEdit.currentPath != mnriPath:
            self._mnriLineEdit.setCurrentPath(mnriPath)

        # Create CLI Node if necessary
        if self._cliNode is None:
            self._cliNode = slicer.cli.createNode(slicer.modules.simplertk)

        # Add or remove CLI observer depending on if the execution is synchronous
        updateCliObserver = self.addObserver if not isCliSynchronous else self.removeObserver
        updateCliObserver(self._cliNode, self._cliNode.StatusModifiedEvent, self.onCLIModified)

        # Reconstruct the geometry
        self._cliNode = self._logic.reconstruct(mnriPath, cliNode=self._cliNode, sync=isCliSynchronous)

        # Load the reconstructed geometry if synchronous
        if isCliSynchronous:
            self.onCLIModified(self._cliNode, self._cliNode.StatusModifiedEvent)

        self.updateReconstructButtonEnabled()
        return self._cliNode

    def reconstruct_odd(self, mnriPath, isCliSynchronous):
        # Synchronize line edit file path with input file path if necessary
        if self._mnriLineEdit.currentPath != mnriPath:
            self._mnriLineEdit.setCurrentPath(mnriPath)

        # Create CLI Node if necessary
        if self._cliNode is None:
            self._cliNode = slicer.cli.createNode(slicer.modules.simplertk)

        # Add or remove CLI observer depending on if the execution is synchronous
        updateCliObserver = self.addObserver if not isCliSynchronous else self.removeObserver
        updateCliObserver(self._cliNode, self._cliNode.StatusModifiedEvent, self.onCLIModified)

        # Reconstruct the geometry
        self._cliNode = self._logic.reconstruct_odd(mnriPath, cliNode=self._cliNode, sync=True)

        # Load the reconstructed geometry if synchronous
        if isCliSynchronous:
            self.onCLIModified_odd(self._cliNode, self._cliNode.StatusModifiedEvent)
            self.reconstruct_even(isCliSynchronous=True, mnriPath = self.evenMnriPath)
        self.updateReconstructButtonEnabled()
        self.onReconstructedfortwoimage(self._cliNode)
        return self._cliNode
    def reconstruct_even(self, mnriPath, isCliSynchronous):
        # Synchronize line edit file path with input file path if necessary
        # if self._mnriLineEdit.currentPath != mnriPath:
        #     self._mnriLineEdit.setCurrentPath(mnriPath)

        # Create CLI Node if necessary
        if self._cliNode is None:
            self._cliNode = slicer.cli.createNode(slicer.modules.simplertk)

        # Add or remove CLI observer depending on if the execution is synchronous
        updateCliObserver = self.addObserver if not isCliSynchronous else self.removeObserver
        updateCliObserver(self._cliNode, self._cliNode.StatusModifiedEvent, self.onCLIModified)

        # Reconstruct the geometry
        self._cliNode = self._logic.reconstruct_even(mnriPath, cliNode=self._cliNode, sync=True)

        # Load the reconstructed geometry if synchronous
        if isCliSynchronous:
            self.onCLIModified_even(self._cliNode, self._cliNode.StatusModifiedEvent)
            self.integratTwoRawFiles(self._dir_path)
        self.updateReconstructButtonEnabled()
        
        

        return self._cliNode    
    def onCLIModified_odd(self, cliNode, event):
        logging.info('{}:{}'.format(cliNode.GetParameterAsString('output'), cliNode.GetStatusString()))

        if self._cliNode.GetErrorText():
            logging.debug('{}\n'.format(self._cliNode.GetErrorText()))

        if cliNode.GetStatusString() == 'Scheduled':
            self.addProgressBar.emit(self._progressText)

        if not cliNode.IsBusy():
            self.removeProgressBar.emit(self._progressText)

            # if cliNode.GetStatusString() == 'Completed':
            #     self.onReconstructed_odd(cliNode)
        self.updateReconstructButtonEnabled()
    def onCLIModified_even(self, cliNode, event):
        logging.info('{}:{}'.format(cliNode.GetParameterAsString('output'), cliNode.GetStatusString()))

        if self._cliNode.GetErrorText():
            logging.debug('{}\n'.format(self._cliNode.GetErrorText()))

        if cliNode.GetStatusString() == 'Scheduled':
            self.addProgressBar.emit(self._progressText)

        if not cliNode.IsBusy():
            self.removeProgressBar.emit(self._progressText)

            # if cliNode.GetStatusString() == 'Completed':
            #     self.onReconstructed_even(cliNode)
        self.updateReconstructButtonEnabled()
    def onCLIModified(self, cliNode, event):
        logging.info('{}:{}'.format(cliNode.GetParameterAsString('output'), cliNode.GetStatusString()))

        if self._cliNode.GetErrorText():
            logging.debug('{}\n'.format(self._cliNode.GetErrorText()))

        if cliNode.GetStatusString() == 'Scheduled':
            self.addProgressBar.emit(self._progressText)

        if not cliNode.IsBusy():
            self.removeProgressBar.emit(self._progressText)

            if cliNode.GetStatusString() == 'Completed':
                self.onReconstructed(cliNode)
        self.updateReconstructButtonEnabled()
    def integratTwoRawFiles(self, dir_path):
        
        mhdfilepath1 = os.path.join(dir_path,"frame1/reconstructed-volume1.raw")
        # if os.path.exists(mhdfilepath1):
        #     self.itkimage1 = sitk.ReadImage(mhdfilepath1)
        mhdfilepath2 = os.path.join(dir_path,"frame2/reconstructed-volume2.raw")
        mhdfilepath3 = os.path.join(dir_path,"reconstructed-volume1.raw")
        # if not os.path.exists(mhdfilepath2):
        #     time.sleep(30)
        # if not os.path.exists(mhdfilepath3):
        #     time.sleep(30)
        
        num_type = numpy.uint16
        with open(mhdfilepath1, "rb") as rawfile:
            self.volume1 = numpy.frombuffer(bytearray(rawfile.read()), dtype=num_type)
        with open(mhdfilepath2, "rb") as rawfile:
            self.volume2 = numpy.frombuffer(bytearray(rawfile.read()), dtype=num_type)    
        with open(mhdfilepath3, "wb") as raw_file:
            raw_file.write(bytearray(self.volume1.astype(self.volume1.dtype).flatten()))         
            raw_file.write(bytearray(self.volume2.astype(self.volume2.dtype).flatten()))
        shutil.copy(os.path.join(dir_path,"frame1/reconstructed-volume1.mhd"), os.path.join(dir_path,"reconstructed-volume1.mhd"))
        with open(os.path.join(dir_path,"frame1/reconstructed-volume1.mhd"), "r") as mhdfile:
            s = mhdfile.read()
            # Read grid dimensions
        m = re.search('DimSize = ([0-9]*) ([0-9]*) ([0-9]*)', s)
        dimstr = 'DimSize = ' + m.group(1) + " " + m.group(2) + " " + m.group(3) 
        dimstr1 = 'DimSize = ' + m.group(1) + " " + m.group(2) + " " + str(int(m.group(3)) * 2) 
        s = s.replace(dimstr, dimstr1)
        with open(os.path.join(dir_path,"reconstructed-volume1.mhd"), "w") as mhdfile:
            mhdfile.write(s)
        self._dataLoaderWidget.loadData(os.path.join(dir_path,"reconstructed-volume1.mhd"))   
    def onReconstructed(self, cliNode):
        # Load reconstructed volume
        logging.info('Loading: {}'.format(cliNode.GetParameterAsString('output')))
        if self._dataLoaderWidget is not None:
            self._reconstructedVolume = self._dataLoaderWidget.loadData(cliNode.GetParameterAsString('output'))
        else:
            self._reconstructedVolume = slicer.util.loadVolume(cliNode.GetParameterAsString('output'))
        if self._reconstructedVolume is not None:
            
            self._volumeFiltersUI.setEnabled(True)
            mnri_settings = self._logic.MNRISettings(self._mnriLineEdit.currentPath)
            filter = mnri_settings.value('SieraRE/ProjSmoothFilterType', '').lower()
            kernelSize = mnri_settings.value('SieraRE/ProjSmoothFilterW')
            if filter == 'median':
                self._volumeFiltersLogic.applyMedianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'gauss':
                self._volumeFiltersLogic.applyGaussianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'lowpass':
                self._volumeFiltersLogic.applySharpenFilter(self._reconstructedVolume)

        # Cleanup MHD file
        # mhdFilePath = os.path.join(cliNode.GetParameterAsString('path'), cliNode.GetParameterAsString('regexp'))
        # self._logic.cleanupMhdFile(mhdFilePath)

        # Save MNRI file path
        self._mnriLineEdit.addCurrentPathToHistory()
        ExportDirectorySettings.save(self._mnriLineEdit.currentPath)

        # Save MNRI directory as next session direction
        qt.QSettings().setValue("SessionDirectory", os.path.dirname(self._mnriLineEdit.currentPath))
    def onReconstructedfortwoimage(self, cliNode):
        # Load reconstructed volume
        logging.info('Loading: {}'.format(cliNode.GetParameterAsString('output')))
        if self._dataLoaderWidget is not None:
            Strtmp = os.path.join(self._dir_path ,"reconstructed-volume1.mhd")
            self._reconstructedVolume = self._dataLoaderWidget.loadData(Strtmp)
        else:
            Strtmp = os.path.join(self._dir_path ,"reconstructed-volume1.mhd")
            self._reconstructedVolume = slicer.util.loadVolume(Strtmp)
        if self._reconstructedVolume is not None:
            
            self._volumeFiltersUI.setEnabled(True)
            mnrifilepath = os.path.join(self._dir_path ,"NAOMICT_UTF8.mnri")
            mnri_settings = self._logic.MNRISettings(mnrifilepath)
            filter = mnri_settings.value('SieraRE/ProjSmoothFilterType', '').lower()
            kernelSize = mnri_settings.value('SieraRE/ProjSmoothFilterW')
            if filter == 'median':
                self._volumeFiltersLogic.applyMedianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'gauss':
                self._volumeFiltersLogic.applyGaussianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'lowpass':
                self._volumeFiltersLogic.applySharpenFilter(self._reconstructedVolume)

    def onReconstructed_even(self, cliNode):
        # Load reconstructed volume
        logging.info('Loading: {}'.format(cliNode.GetParameterAsString('output')))
        if self._dataLoaderWidget is not None:
            self._reconstructedVolume = self._dataLoaderWidget.loadData(cliNode.GetParameterAsString('output'))
        else:
            self._reconstructedVolume = slicer.util.loadVolume(cliNode.GetParameterAsString('output'))
        if self._reconstructedVolume is not None:
            # msg = qt.QMessageBox()
            # msg.setText(self._reconstructedVolume)
            # msg.exec_()
            self._volumeFiltersUI.setEnabled(True)
            mnri_settings = self._logic.MNRISettings(self.evenMnriPath)
            filter = mnri_settings.value('SieraRE/ProjSmoothFilterType', '').lower()
            kernelSize = mnri_settings.value('SieraRE/ProjSmoothFilterW')
            if filter == 'median':
                self._volumeFiltersLogic.applyMedianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'gauss':
                self._volumeFiltersLogic.applyGaussianFilter(self._reconstructedVolume, kernelSize)
            elif filter == 'lowpass':
                self._volumeFiltersLogic.applySharpenFilter(self._reconstructedVolume)
    def clean(self):
        # Cancel previously running reconstruction if necessary on session reload
        if self._cliNode:
            self._cliNode.Cancel()
            removeNodeFromMRMLScene(self._cliNode)
            self._cliNode = None


class RFReconstructionLogic(ScriptedLoadableModuleLogic):

    class Settings:
        """Convenient class to access INI values in original type"""
        def __init__(self, ini_file_path):
            if not os.path.isfile(ini_file_path):
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), ini_file_path)
            
            self.settings = qt.QSettings()
            self.settings.setIniCodec("UTF-8")        

            self.settings = qt.QSettings(ini_file_path, qt.QSettings.IniFormat)
            self.settings.setIniCodec("UTF-8")  
        def value(self, name, default=None):
            """Read INI value with input name section and return value as float if number else as str"""
            try:
                value = self.settings.value(name, default)
                if value is None:
                    return ""
                else:    
                    return float(value)
            except ValueError:
                # value =value.encode("utf-8")
                # value = value.decode("utf-8")
                return value        
        def sectionValue(self, section, name, default=None):
            return self.value('{}/{}'.format(section, name), default)

    class MNRISettings(Settings):
        """Convenient class to access MNRI values in original type"""
        def __init__(self, mnri_file_path):
            # tmpfile =  os.path.join(os.path.dirname(mnri_file_path), "NAOMICT_UTF8.mnri")
            # blockSize = 1048576
            
            # rawdata = open(mnri_file_path, "r").read()
            # result = chardet.detect(rawdata)
            # # charenc = result['encoding']
            # msg =qt.QMessageBox()
            # msg.setText(result)
            # msg.exec_()
            # if charenc != "UTF-8":
            #     with open(mnri_file_path,"r") as sourceFile:
            #         with codecs.open(tmpfile,"w",encoding="UTF-8") as targetFile:
            #             while True:
            #                 contents = sourceFile.read(blockSize)
            #                 if not contents:
            #                     break
            #                 targetFile.write(contents)
            #     os.remove(mnri_file_path)
            #     os.rename(tmpfile, mnri_file_path)
            super().__init__(mnri_file_path)

    def __init__(self):
        super(RFReconstructionLogic, self).__init__()
        self._tmpSymlink = TemporarySymlink()

    @staticmethod
    def stripWhiteSpace(inStr):
        """
        Strip whitespace from lines of the input string.

        Example :
            inStr = "\n    Line 1   \n   Line  2   \n"
            stripWhiteSpace(inStr) # -> "Line 1\nLine  2"
        """
        return "\n".join([s.strip() for s in inStr.split("\n") if s])

    def convertMnriToMhd(self, mnri_file_path):
        """
        Creates an mhd string corresponding to the information contained in the input mnri file path.

        :param mnri_file_path: Path to the mnri file
        :raises: ValueError if MNRI file doesn't exist
        :return: str containing the mhd information extracted from the mnri file
        """

        # read MNRI file as .ini settings file
        mnri_settings = self.MNRISettings(mnri_file_path)
        # msg = qt.QMessageBox()
        # msg.setText(mnri_file_path)
        # msg.exec_()
        # Extract values from mnri settings and try to convert them to float if possible
        data_names = ["ImageFormat", "FrameWidth", "FrameHeight", "FrameCount", "FrameLengthWidth", "FrameLengthHeight",
                      "FrameNameDigit", "FrameFolder", "FrameBaseName", "ImageFileExt"]
        mnri_data = {name: mnri_settings.sectionValue('Frame', name) for name in data_names}

        # msg = qt.QMessageBox()
        # msg.setText(mnri_settings.value("Frame/ImageFormat"))
        # msg.exec_()

        mnri_data["XSpacing"] = mnri_data["FrameLengthWidth"] / mnri_data["FrameWidth"]
        mnri_data["YSpacing"] = mnri_data["FrameLengthHeight"] / mnri_data["FrameHeight"]
        mnri_data["LastFrameIndex"] = mnri_data["FrameCount"] - 1

        imageFormatToElementType = {
            'Bmp':'MET_USHORT',
            'Raw8': 'MET_UCHAR',
            'Raw16': 'MET_USHORT'  # special meaning for RTK (see rtkProjectionsReader)
        }

        mnri_data['ElementType'] = imageFormatToElementType[mnri_data["ImageFormat"]]

       
        # Create MHD file pattern based and fill it with mnri data
        mhd = """
            ObjectType = Image
            NDims = 3
            DimSize = {FrameWidth:.0f} {FrameHeight:.0f} {FrameCount:.0f}
            ElementType = {ElementType}
            HeaderSize = -1
            ElementSize = 1 1 1
            ElementSpacing = {XSpacing:.5f} {YSpacing:.5f} 1
            ElementByteOrderMSB = False
            ElementDataFile = {FrameFolder}/{FrameBaseName}%0{FrameNameDigit:.0f}d.{ImageFileExt} 0 {LastFrameIndex:.0f} 1
            """.format(**mnri_data)

        return self.stripWhiteSpace(mhd)

    def createMhdFile(self, mnri_file_path):
        """
        Reads an MNRI file and creates an mhd file in the same directory as the source MNRI file

        :param mnri_file_path: full path to an existing MNRI file
        :raises: ValueError if MNRI file doesn't exist
        :return: full path to the created MHD file
        """
        mhd_file_text = self.convertMnriToMhd(mnri_file_path)

        out_file_name = os.path.basename(mnri_file_path).replace(".mnri", ".mhd")
        output_path = os.path.join(os.path.dirname(mnri_file_path), out_file_name)

        with open(output_path, "w") as f:
            f.write(mhd_file_text)

        return output_path

    def convertMnriToMhd1(self, mnri_file_path):
        """
        Creates an mhd string corresponding to the information contained in the input mnri file path.

        :param mnri_file_path: Path to the mnri file
        :raises: ValueError if MNRI file doesn't exist
        :return: str containing the mhd information extracted from the mnri file
        """

        # read MNRI file as .ini settings file
        mnri_settings = self.MNRISettings(mnri_file_path)

        # Extract values from mnri settings and try to convert them to float if possible
        data_names = ["ImageFormat", "FrameWidth", "FrameHeight", "FrameCount1", "FrameLengthWidth", "FrameLengthHeight",
                      "FrameNameDigit", "FrameFolder", "FrameBaseName", "ImageFileExt"]
        mnri_data = {name: mnri_settings.sectionValue('Frame', name) for name in data_names}

        mnri_data["XSpacing"] = mnri_data["FrameLengthWidth"] / mnri_data["FrameWidth"]
        mnri_data["YSpacing"] = mnri_data["FrameLengthHeight"] / mnri_data["FrameHeight"]
        mnri_data["LastFrameIndex"] = mnri_data["FrameCount1"] - 1

        imageFormatToElementType = {
            'Bmp':'MET_USHORT',
            'Raw8': 'MET_UCHAR',
            'Raw16': 'MET_USHORT'  # special meaning for RTK (see rtkProjectionsReader)
        }
        mnri_data['ElementType'] = imageFormatToElementType[mnri_data["ImageFormat"]]

        # Create MHD file pattern based and fill it with mnri data
        mhd = """
            ObjectType = Image
            NDims = 3
            DimSize = {FrameWidth:.0f} {FrameHeight:.0f} {FrameCount1:.0f}
            ElementType = {ElementType}
            HeaderSize = -1
            ElementSize = 1 1 1
            ElementSpacing = {XSpacing:.5f} {YSpacing:.5f} 1
            ElementByteOrderMSB = False
            ElementDataFile = {FrameFolder}/{FrameBaseName}%0{FrameNameDigit:.0f}d.{ImageFileExt} 0 {LastFrameIndex:.0f} 1
            """.format(**mnri_data)

        return self.stripWhiteSpace(mhd)

    def createMhdFile1(self, mnri_file_path):
        """
        Reads an MNRI file and creates an mhd file in the same directory as the source MNRI file

        :param mnri_file_path: full path to an existing MNRI file
        :raises: ValueError if MNRI file doesn't exist
        :return: full path to the created MHD file
        """
        mhd_file_text = self.convertMnriToMhd1(mnri_file_path)

        out_file_name = os.path.basename(mnri_file_path).replace(".mnri", ".mhd")
        output_path = os.path.join(os.path.dirname(mnri_file_path), out_file_name)

        with open(output_path, "w") as f:
            f.write(mhd_file_text)

        return output_path
    def convertMnriToMhd2(self, mnri_file_path):
        """
        Creates an mhd string corresponding to the information contained in the input mnri file path.

        :param mnri_file_path: Path to the mnri file
        :raises: ValueError if MNRI file doesn't exist
        :return: str containing the mhd information extracted from the mnri file
        """

        # read MNRI file as .ini settings file
        mnri_settings = self.MNRISettings(mnri_file_path)

        # Extract values from mnri settings and try to convert them to float if possible
        data_names = ["ImageFormat", "FrameWidth", "FrameHeight", "FrameCount2", "FrameLengthWidth", "FrameLengthHeight",
                      "FrameNameDigit", "FrameFolder", "FrameBaseName", "ImageFileExt"]
        mnri_data = {name: mnri_settings.sectionValue('Frame', name) for name in data_names}

        mnri_data["XSpacing"] = mnri_data["FrameLengthWidth"] / mnri_data["FrameWidth"]
        mnri_data["YSpacing"] = mnri_data["FrameLengthHeight"] / mnri_data["FrameHeight"]
        mnri_data["LastFrameIndex"] = mnri_data["FrameCount2"] - 1

        imageFormatToElementType = {
            'Bmp':'MET_USHORT',
            'Raw8': 'MET_UCHAR',
            'Raw16': 'MET_USHORT'  # special meaning for RTK (see rtkProjectionsReader)
        }
        mnri_data['ElementType'] = imageFormatToElementType[mnri_data["ImageFormat"]]

        # Create MHD file pattern based and fill it with mnri data
        mhd = """
            ObjectType = Image
            NDims = 3
            DimSize = {FrameWidth:.0f} {FrameHeight:.0f} {FrameCount2:.0f}
            ElementType = {ElementType}
            HeaderSize = -1
            ElementSize = 1 1 1
            ElementSpacing = {XSpacing:.5f} {YSpacing:.5f} 1
            ElementByteOrderMSB = False
            ElementDataFile = {FrameFolder}/{FrameBaseName}%0{FrameNameDigit:.0f}d.{ImageFileExt} 0 {LastFrameIndex:.0f} 1
            """.format(**mnri_data)

        return self.stripWhiteSpace(mhd)

    def createMhdFile2(self, mnri_file_path):
        """
        Reads an MNRI file and creates an mhd file in the same directory as the source MNRI file

        :param mnri_file_path: full path to an existing MNRI file
        :raises: ValueError if MNRI file doesn't exist
        :return: full path to the created MHD file
        """
        mhd_file_text = self.convertMnriToMhd2(mnri_file_path)

        out_file_name = os.path.basename(mnri_file_path).replace(".mnri", ".mhd")
        output_path = os.path.join(os.path.dirname(mnri_file_path), out_file_name)

        with open(output_path, "w") as f:
            f.write(mhd_file_text)

        return output_path

    def createCLIParameters(self, mnri_file_path, output_path=None):

        # Create MHD file in the MRNIPath
        mhdFilePath = self.createMhdFile(mnri_file_path)
        self._tmpSymlink.setTargetDir(os.path.dirname(mhdFilePath))
        mhdDirPath = self._tmpSymlink.getSymlinkPath()

        if output_path is None:
            output_path = os.path.join(mhdDirPath, "reconstructed-volume.mhd")

        mnri_settings = self.MNRISettings(mnri_file_path)

        
        spacing = mnri_settings.value("Frame/FrameLengthWidth") / mnri_settings.value("Frame/FrameWidth")
        sign = -1 # maybe the following ?  1 if mnri_settings.value("Frame/ImageFlipNeed") != 'None' else -1
        angleSign = -1 if mnri_settings.value("Geometry/AntiClkRotDir") == 0 else 1

        settings = qt.QSettings()
        settings.beginGroup("Reconstruction")
        hardware = settings.value("hardware", "cuda")
        settings.endGroup()

        pixel_depth = int(mnri_settings.value("Frame/PixelDepth"))
        if pixel_depth <= 13:
            divisions = 1
            subsetSize = 6
        else:
            divisions = 3
            subsetSize = 30

        preset = int(mnri_settings.value('Volume/TFPresetIndex'))
        CTValuePreset = qt.QSettings('CTValuePreset.ini', qt.QSettings.IniFormat)  # File must be next to RFViewer.ini
        airvalue = CTValuePreset.value('CTValuePreset{:04d}_Air'.format(preset), "0.0")
        watervalue = CTValuePreset.value('CTValuePreset{:04d}_Water'.format(preset), "0.018")
        
        tomoTheta = numpy.deg2rad(mnri_settings.value("Geometry/TomoTheta") - 90)
        tomoDist = numpy.sin(tomoTheta) * mnri_settings.value("Geometry/XSrcDetectDist")
        
        offsetX = mnri_settings.value("Geometry/OffsetHoriz") * spacing
        offsetY = mnri_settings.value("Geometry/OffsetVertical") * spacing

        parameters = {
            # IO
            "path": mhdDirPath,
            "regexp": os.path.basename(mhdFilePath),
            "output": output_path,
            # Geometry
            "nproj": mnri_settings.value("Frame/FrameCount"),
            "sdd": mnri_settings.value("Geometry/XSrcDetectDist"),  # Source to detector distance (mm)
            "sid": mnri_settings.value("Geometry/XSrcObjectDist"),  # Source to isocenter distance (mm)
            "first_angle": mnri_settings.value("Geometry/InitAngle"), # First angle in degrees
            "proj_iso_x": sign * (offsetX + mnri_settings.value("Geometry/DetectOffset")),
            "proj_iso_y": sign * (offsetY + tomoDist),
            "source_x": sign * offsetX,
            "source_y": sign * offsetY,
            "arc": angleSign * mnri_settings.value("Geometry/TotalAngle"),
            "in_angle": mnri_settings.value("Geometry/OffsetOrient"),
            "out_angle": "0",
            "rad_crop_perc": mnri_settings.value("Process/RadiusCropPercentage", default=7),  # Percentage of cylinder crop due to beam hardening
            # FDK
            "hann": mnri_settings.value("Process/FrequencyCut"),  # Cut frequency for hann window in ]0, 1] (0. disables it)
            "hardware": hardware, # cuda or cpu
            "lowmem": True,
            "divisions": divisions,
            "subsetsize": subsetSize,
            "mask": False,
            # Output
            "scalarType": "Short",
            "dimension": '{}, {}, {}'.format(
                int(mnri_settings.value("BackProjection/VolXDim")),
                int(mnri_settings.value("BackProjection/VolYDim")),
                int(mnri_settings.value("BackProjection/VolZDim"))
            ),  # Output dimension
            "spacing": '{}, {}, {}'.format(
            spacing * float(mnri_settings.value("BackProjection/VolXPitch")),
            spacing * float(mnri_settings.value("BackProjection/VolYPitch")),
            spacing * float(mnri_settings.value("BackProjection/VolZPitch"))
            ),  # Output spacing
            "neworigin": '{},{},{}'.format(
                - mnri_settings.value("Frame/FrameLengthWidth") / 2 + offsetX,
                - mnri_settings.value("Frame/FrameLengthHeight") / 2,
                0), # New origin of input projections (before pre-processing)
            # "direction": '0, 0, -1, 1, 0, 0, 0, 1, 0', # Output direction -> 0 1 0 0 0 1 -1 0 0
            #"direction": '0, 1, 0, 0, 0, 1, -1, 0, 0', # Output direction -> 0 0 -1 1 0 0 0 1 0 -> 0 0 -1 -1 0 0 0 -1 0
            "origin": '{},{},{}'.format(
                mnri_settings.value("BackProjection/VolXStart") * spacing,
                mnri_settings.value("BackProjection/VolYStart") * spacing,
                mnri_settings.value("BackProjection/VolZStart") * spacing
            ), # new origin
            "airvalue": airvalue,
            "watervalue": watervalue
            }

        if mnri_settings.value("Process/HFilterType") == "Median":
            parameters["radius"] = '{},{}'.format(
                int(mnri_settings.value("Process/HFilterMaskRadius")),
                int(mnri_settings.value("Process/VFilterMaskRadius"))
            )  # Radius of neighborhood for conditionl median filtering
            parameters["multiplier"] = '1'
        parameters["multiplier"] = '1'    
        iDark, i0 = RFReconstructionLogic.range(mnri_settings)

        if iDark is not None:
            parameters["idark"] = iDark

        if i0 is not None:
            parameters["i0"] = i0

        return parameters
            
    def createCLIParameters1(self, mnri_file_path, output_path=None):

        # Create MHD file in the MRNIPath
        mhdFilePath = self.createMhdFile1(mnri_file_path)
        self._tmpSymlink.setTargetDir(os.path.dirname(mhdFilePath))
        mhdDirPath = self._tmpSymlink.getSymlinkPath()

        if output_path is None:
            output_path = os.path.join(mhdDirPath, "reconstructed-volume1.mhd")

        mnri_settings = self.MNRISettings(mnri_file_path)

        
        spacing = mnri_settings.value("Frame/FrameLengthWidth") / mnri_settings.value("Frame/FrameWidth")
        sign = -1 # maybe the following ?  1 if mnri_settings.value("Frame/ImageFlipNeed") != 'None' else -1
        angleSign = -1 if mnri_settings.value("Geometry/AntiClkRotDir") == 0 else 1

        settings = qt.QSettings()
        settings.beginGroup("Reconstruction")
        hardware = settings.value("hardware", "cuda")
        settings.endGroup()

        pixel_depth = int(mnri_settings.value("Frame/PixelDepth"))
        if pixel_depth <= 13:
            divisions = 1
            subsetSize = 6
        else:
            divisions = 3
            subsetSize = 30

        preset = int(mnri_settings.value('Volume/TFPresetIndex'))
        CTValuePreset = qt.QSettings('CTValuePreset.ini', qt.QSettings.IniFormat)  # File must be next to RFViewer.ini
        airvalue = CTValuePreset.value('CTValuePreset{:04d}_Air'.format(preset), "0.0")
        watervalue = CTValuePreset.value('CTValuePreset{:04d}_Water'.format(preset), "0.018")
        
        tomoTheta = numpy.deg2rad(mnri_settings.value("Geometry/TomoTheta1") - 90)
        tomoDist = numpy.sin(tomoTheta) * mnri_settings.value("Geometry/XSrcDetectDist1")
        
        offsetX = mnri_settings.value("Geometry/OffsetHoriz1") * spacing
        offsetY = mnri_settings.value("Geometry/OffsetVertical1") * spacing

        parameters = {
            # IO
            "path": mhdDirPath,
            "regexp": os.path.basename(mhdFilePath),
            "output": output_path,
            # Geometry
            "nproj": mnri_settings.value("Frame/FrameCount1"),
            "sdd": mnri_settings.value("Geometry/XSrcDetectDist1"),  # Source to detector distance (mm)
            "sid": mnri_settings.value("Geometry/XSrcObjectDist1"),  # Source to isocenter distance (mm)
            "first_angle": mnri_settings.value("Geometry/InitAngle1"), # First angle in degrees
            "proj_iso_x": sign * (offsetX + mnri_settings.value("Geometry/DetectOffset1")),
            "proj_iso_y": sign * (offsetY + tomoDist),
            "source_x": sign * offsetX,
            "source_y": sign * offsetY,
            "arc": angleSign * mnri_settings.value("Geometry/TotalAngle1"),
            "in_angle": mnri_settings.value("Geometry/OffsetOrient1"),
            "out_angle": "0",
            "rad_crop_perc": mnri_settings.value("Process/RadiusCropPercentage", default=7),  # Percentage of cylinder crop due to beam hardening
            # FDK
            "hann": mnri_settings.value("Process/FrequencyCut"),  # Cut frequency for hann window in ]0, 1] (0. disables it)
            "hardware": hardware, # cuda or cpu
            "lowmem": True,
            "divisions": divisions,
            "subsetsize": subsetSize,
            "mask": False,
            # Output
            "scalarType": "Short",
            "dimension": '{}, {}, {}'.format(
                int(mnri_settings.value("BackProjection/VolXDim1")),
                int(mnri_settings.value("BackProjection/VolYDim1")),
                int(mnri_settings.value("BackProjection/VolZDim1"))
            ),  # Output dimension
            "spacing": '{}, {}, {}'.format(
            spacing * float(mnri_settings.value("BackProjection/VolXPitch1")),
            spacing * float(mnri_settings.value("BackProjection/VolYPitch1")),
            spacing * float(mnri_settings.value("BackProjection/VolZPitch1"))
            ),  # Output spacing
            "neworigin": '{},{},{}'.format(
                - mnri_settings.value("Frame/FrameLengthWidth") / 2 + offsetX,
                - mnri_settings.value("Frame/FrameLengthHeight") / 2,
                0), # New origin of input projections (before pre-processing)
            # "direction": '0, 0, -1, 1, 0, 0, 0, 1, 0', # Output direction -> 0 1 0 0 0 1 -1 0 0
            #"direction": '0, 1, 0, 0, 0, 1, -1, 0, 0', # Output direction -> 0 0 -1 1 0 0 0 1 0 -> 0 0 -1 -1 0 0 0 -1 0
            "origin": '{},{},{}'.format(
                mnri_settings.value("BackProjection/VolXStart1") * spacing,
                mnri_settings.value("BackProjection/VolYStart1") * spacing,
                mnri_settings.value("BackProjection/VolZStart1") * spacing
            ), # new origin
            "airvalue": airvalue,
            "watervalue": watervalue
            }

        if mnri_settings.value("Process/HFilterType") == "Median":
            parameters["radius"] = '{},{}'.format(
                int(mnri_settings.value("Process/HFilterMaskRadius")),
                int(mnri_settings.value("Process/VFilterMaskRadius"))
            )  # Radius of neighborhood for conditional median filtering
            parameters["multiplier"] = '1'
            
        iDark, i0 = RFReconstructionLogic.range(mnri_settings)

        if iDark is not None:
            parameters["idark"] = iDark

        if i0 is not None:
            parameters["i0"] = i0

        return parameters
            
    def createCLIParameters2(self, mnri_file_path, output_path=None):

        # Create MHD file in the MRNIPath
        mhdFilePath = self.createMhdFile2(mnri_file_path)
        self._tmpSymlink.setTargetDir(os.path.dirname(mhdFilePath))
        mhdDirPath = self._tmpSymlink.getSymlinkPath()

        if output_path is None:
            output_path = os.path.join(mhdDirPath, "reconstructed-volume2.mhd")

        mnri_settings = self.MNRISettings(mnri_file_path)

        
        spacing = mnri_settings.value("Frame/FrameLengthWidth") / mnri_settings.value("Frame/FrameWidth")
        sign = -1 # maybe the following ?  1 if mnri_settings.value("Frame/ImageFlipNeed") != 'None' else -1
        angleSign = -1 if mnri_settings.value("Geometry/AntiClkRotDir") == 0 else 1

        settings = qt.QSettings()
        settings.beginGroup("Reconstruction")
        hardware = settings.value("hardware", "cuda")
        settings.endGroup()

        pixel_depth = int(mnri_settings.value("Frame/PixelDepth"))
        if pixel_depth <= 13:
            divisions = 1
            subsetSize = 6
        else:
            divisions = 3
            subsetSize = 30

        preset = int(mnri_settings.value('Volume/TFPresetIndex'))
        CTValuePreset = qt.QSettings('CTValuePreset.ini', qt.QSettings.IniFormat)  # File must be next to RFViewer.ini
        airvalue = CTValuePreset.value('CTValuePreset{:04d}_Air'.format(preset), "0.0")
        watervalue = CTValuePreset.value('CTValuePreset{:04d}_Water'.format(preset), "0.018")
        
        tomoTheta = numpy.deg2rad(mnri_settings.value("Geometry/TomoTheta2") - 90)
        tomoDist = numpy.sin(tomoTheta) * mnri_settings.value("Geometry/XSrcDetectDist2")
        
        offsetX = mnri_settings.value("Geometry/OffsetHoriz2") * spacing
        offsetY = mnri_settings.value("Geometry/OffsetVertical2") * spacing

        parameters = {
            # IO
            "path": mhdDirPath,
            "regexp": os.path.basename(mhdFilePath),
            "output": output_path,
            # Geometry
            "nproj": mnri_settings.value("Frame/FrameCount2"),
            "sdd": mnri_settings.value("Geometry/XSrcDetectDist2"),  # Source to detector distance (mm)
            "sid": mnri_settings.value("Geometry/XSrcObjectDist2"),  # Source to isocenter distance (mm)
            "first_angle": mnri_settings.value("Geometry/InitAngle2"), # First angle in degrees
            "proj_iso_x": sign * (offsetX + mnri_settings.value("Geometry/DetectOffset2")),
            "proj_iso_y": sign * (offsetY + tomoDist),
            "source_x": sign * offsetX,
            "source_y": sign * offsetY,
            "arc": angleSign * mnri_settings.value("Geometry/TotalAngle2"),
            "in_angle": mnri_settings.value("Geometry/OffsetOrient2"),
            "out_angle": "0",
            "rad_crop_perc": mnri_settings.value("Process/RadiusCropPercentage", default=7),  # Percentage of cylinder crop due to beam hardening
            # FDK
            "hann": mnri_settings.value("Process/FrequencyCut"),  # Cut frequency for hann window in ]0, 1] (0. disables it)
            "hardware": hardware, # cuda or cpu
            "lowmem": True,
            "divisions": divisions,
            "subsetsize": subsetSize,
            "mask": False,
            # Output
            "scalarType": "Short",
            "dimension": '{}, {}, {}'.format(
                int(mnri_settings.value("BackProjection/VolXDim2")),
                int(mnri_settings.value("BackProjection/VolYDim2")),
                int(mnri_settings.value("BackProjection/VolZDim2"))
            ),  # Output dimension
            "spacing": '{}, {}, {}'.format(
            spacing * float(mnri_settings.value("BackProjection/VolXPitch2")),
            spacing * float(mnri_settings.value("BackProjection/VolYPitch2")),
            spacing * float(mnri_settings.value("BackProjection/VolZPitch2"))
            ),  # Output spacing
            "neworigin": '{},{},{}'.format(
                - mnri_settings.value("Frame/FrameLengthWidth") / 2 + offsetX,
                - mnri_settings.value("Frame/FrameLengthHeight") / 2,
                0), # New origin of input projections (before pre-processing)
            # "direction": '0, 0, -1, 1, 0, 0, 0, 1, 0', # Output direction -> 0 1 0 0 0 1 -1 0 0
            #"direction": '0, 1, 0, 0, 0, 1, -1, 0, 0', # Output direction -> 0 0 -1 1 0 0 0 1 0 -> 0 0 -1 -1 0 0 0 -1 0
            "origin": '{},{},{}'.format(
                mnri_settings.value("BackProjection/VolXStart2") * spacing,
                mnri_settings.value("BackProjection/VolYStart2") * spacing,
                mnri_settings.value("BackProjection/VolZStart2") * spacing
            ), # new origin
            "airvalue": airvalue,
            "watervalue": watervalue
            }

        if mnri_settings.value("Process/HFilterType") == "Median":
            parameters["radius"] = '{},{}'.format(
                int(mnri_settings.value("Process/HFilterMaskRadius")),
                int(mnri_settings.value("Process/VFilterMaskRadius"))
            )  # Radius of neighborhood for conditional median filtering
            parameters["multiplier"] = '1'
            
        iDark, i0 = RFReconstructionLogic.range(mnri_settings)

        if iDark is not None:
            parameters["idark"] = iDark

        if i0 is not None:
            parameters["i0"] = i0

        return parameters
    @staticmethod
    def imageBits(mnri_settings):
        imageFormatToBits = {'Raw8': 8, 'Raw16': 16}
        return imageFormatToBits[mnri_settings.value("Frame/ImageFormat")]

    @staticmethod
    def range(mnri_settings):
        """Returns the possible range of pixels of the projection frames.
        Frames are normalized between [0, 2^NB] where NB is the number
        of bits per pixel."""
        numberOfBits = RFReconstructionLogic.imageBits(mnri_settings)
        pixelDepth = int(mnri_settings.value("Frame/PixelDepth"))
        if pixelDepth == 16:
            pixelDepth -= 1
        iDark = 0
        i0 = pow(2, pixelDepth)
        return [iDark, i0]

    def cleanupMhdFile(self, mhd_file_path):
        if os.path.exists(mhd_file_path):
            os.remove(mhd_file_path)

    # def getFileContents(self, filePath):
        
    #     imgfile = qt.QFile(filePath)
    #     if not imgfile.open(qt.QIODevice::ReadOnly):
    #        return

    #     stream = qt.QDataStream(imgfile)
    #     stream.setByteOrder(qt.QDataStream::LittleEndian)

    #     qt.QVector<qint16> result
    #     while(stream.atEnd() != null) {
    #         qint16 x;
    #         stream >> x;
    #         result.append(x);
    #     }
    def read_file(self, filename, endian):
        count = int(os.stat(filename).st_size / 2)
        # msg = qt.QMessageBox()
        # msg.setText(count)
        # msg.exec_()
        with open(filename, 'rb') as f:
            result = array('H')
            result.fromfile(f, count)
            if endian != system_endian: result.byteswap()
            return result

    def write_file(self,filename, resultarray):
        if sys.byteorder == "little":
            resultarray.byteswap()
        with open(filename, 'wb') as f:
            resultarray.tofile(f)
            # for item in resultarray:
            #     f.write("%d" % item)
    def int_to_signed_short(self, value):
        return -(value & 0x8000) | (value & 0x7fff)

    def filesubtration(self,totalcount,count, dir_path, filename1, filename2):
        print(filename1)
        print(filename2) 

        img_path = os.path.join(dir_path, "frame/" + filename1)
        img_path1 = os.path.join(dir_path, "frame/"+ filename2)
        tmpcount = int(count//2)
        tmpcount1 = int(totalcount // 2) + tmpcount
        if tmpcount < 10:
            newfilename = "image_00" + str(tmpcount) + ".img"
        elif tmpcount< 100:
            newfilename = "image_0" + str(tmpcount) + ".img"
        else:
            newfilename = "image_" + str(tmpcount) + ".img"
        
        if tmpcount1 < 10:
            newfilename1 = "image_00" + str(tmpcount1) + ".img"
        elif tmpcount1< 100:
            newfilename1 = "image_0" + str(tmpcount1) + ".img"
        else:
            newfilename1 = "image_" + str(tmpcount1) + ".img"

        print(newfilename)
        print(newfilename1) 
        # arraysize = int (os.stat(img_path).st_size / 2 + 1)

        # resultfile = self.read_file(img_path, "little")
        # resultfile1 = self.read_file(img_path1, "little")
        # tmp_result = [None] * len(resultfile);    

        # for i in range(0, len(resultfile)):    
        #     if i< 40 :
        #         tmp_result[i] = resultfile[i] 
        #     else:
        #         tmp_result[i] = resultfile[i] - round(resultfile1[i] * 0.017)     
        
        result_dir = os.path.join(dir_path,"frame_result1")
        if not os.path.exists(result_dir):
            os.mkdir(result_dir)
        
        shutil.copy(img_path, result_dir)
        os.rename(os.path.join(result_dir, filename1), os.path.join(result_dir, newfilename))
        dir = os.path.join(dir_path,"frame1")
        if not os.path.exists(dir):
            os.mkdir(dir)
        shutil.copy(os.path.join(dir_path, "NAOMICT_UTF8.mnri"), dir)
        
        dir = os.path.join(dir_path,"frame1/frame")
        if not os.path.exists(dir):
            os.mkdir(dir)    
        shutil.copy(os.path.join(result_dir, newfilename), dir)
        

        result_dir = os.path.join(dir_path,"frame_result2")
        if not os.path.exists(result_dir):
            os.mkdir(result_dir)

        shutil.copy(img_path1, result_dir)
        os.rename(os.path.join(result_dir, filename2), os.path.join(result_dir, newfilename))
        dir = os.path.join(dir_path,"frame2")
        if not os.path.exists(dir):
            os.mkdir(dir)
        shutil.copy(os.path.join(dir_path, "NAOMICT_UTF8.mnri"), dir)
        dir = os.path.join(dir_path,"frame2/frame")
        if not os.path.exists(dir):
            os.mkdir(dir) 
        shutil.copy(os.path.join(result_dir, newfilename), dir)
        print(os.path.join(result_dir, filename1))
        print(os.path.join(result_dir, filename2))
        print(os.path.join(result_dir, newfilename))
        #     dir = os.path.join(dir_path,"frame2")    
        #     if not os.path.exists(dir):
        #         os.mkdir(dir)
        #     result_img_path = os.path.join(dir_path, "frame2/"+ newfilename)
        #     my_array = np.array( tmp_result , dtype='H')
        #     self.write_file(result_img_path, my_array)
        #     shutil.copy(result_img_path, result_dir)
        # return "ok"
    def converting_files(self, mnri_file_path):
        
        mnri_settings = self.MNRISettings(mnri_file_path)
        # typevalues = mnri_settings.value("Frame/Type")
        # if typevalues == 1:
        dir_path = os.path.dirname(mnri_file_path)
        filecount = int(mnri_settings.value("Frame/FrameCount"))
        print(filecount)
        try:
            rangeValue =  float(mnri_settings.value("Frame/Subtraction"))
        except:
            rangeValue =  0.017
        
        result_dir11 = os.path.join(dir_path,"framecal")
        if not os.path.exists(result_dir11):
            os.mkdir(result_dir11)
        img_path = ""
        # print(rangeValue)
        for i in range(1, filecount, 1):
            j = i - 1
            if i < 10:
                img_path = "image_00" + str(i) + ".img"
            elif i< 100:
                img_path = "image_0" + str(i) + ".img"
            else:
                img_path = "image_" + str(i) + ".img"
            img_file_path = os.path.join(dir_path, "frame/" + img_path)
            print(img_file_path)
            if j < 10:
                img_path1 = "image_00" + str(j) + ".img"
            elif j< 100:
                img_path1 = "image_0" + str(j) + ".img"
            else:
                img_path1 = "image_" + str(j) + ".img"    
            img_file_path1 = os.path.join(dir_path, "frame/" + img_path1)
            # print(img_path1)
            
            resultfile = np.fromfile(img_file_path, dtype=np.uint16)
            resultfile1 = np.fromfile(img_file_path1, dtype=np.uint16)
            print(resultfile)
            print(resultfile1)
            # resultfile = self.read_file(img_path, "little")
            # resultfile1 = self.read_file(img_path1, "little")
            # tmp_result = [None] * len(resultfile);    
            tmp_result = resultfile - resultfile1 * rangeValue  
            


            # image = tmp_result.reshape(616, int(len(tmp_result) / 616))
            
            
            
            # image = rescale(image, scale=0.4, mode='reflect', multichannel=False)

            # theta = np.linspace(0., 180., max(image.shape), endpoint=False)
            # # imagedata = rescale(imagedata, scale=0.4, mode='reflect', multichannel=False)
            # sinogram = radon(image, theta=theta,circle=False)
            # print("sinogram")
            # print(sinogram)
            # reconstruction_fbp = iradon(sinogram, theta=theta,circle=False)
            # reconstruction_sart = iradon_sart(sinogram, theta=theta)
            # reconstruction_sart2 = iradon_sart(sinogram, theta=theta,
            #                        image=reconstruction_sart)
            # print(reconstruction_sart2)
            # np.save(img_path, tmp_result)
            
            # tmp_result.tofile(img_path,dtype=np.uint16)
            # # for i in range(0, len(resultfile)):    
            # #     if i< 40 :
            # #         tmp_result[i] = resultfile[i] 
            # #     else:
            # #         tmp_result[i] = resultfile[i] - round(resultfile1[i] * rangeValue)         

            # # result_img_path = os.path.join(dir_path,resultfile )

            tmp_result = tmp_result
            my_array = np.array( tmp_result , dtype=np.uint16)
            print(my_array)
            my_array.tofile(result_dir11 + "/" + img_path)



            resultfile2 = np.fromfile(result_dir11 + "/" + img_path, dtype=np.uint16)
            print(resultfile2)
            # print(img_path)
            # shutil.copy(result_img_path, result_dir)
        # test = os.listdir(dir_path + "/frame/")
        # for item in test:
        #     if item.endswith(".npy"):
        #         os.remove(os.path.join(dir_path + "/frame", item))
        shutil.copyfile(dir_path+ "/frame/image_000.img", dir_path+ "/framecal/image_000.img")
        os.rename(dir_path + "/" + "frame",dir_path + "/" + "frame_original")
        os.rename(result_dir11,dir_path + "/" + "frame") 

        img_path = ""
        img_path1 = ""
        for i in range(1, filecount, 2 ):  
            j = i - 1  
            if i < 10:
                img_path = "image_00" + str(i) + ".img"
            elif i< 100:
                img_path = "image_0" + str(i) + ".img"
            else:
                img_path = "image_" + str(i) + ".img"
            
            if j < 10:
                img_path1 = "image_00" + str(j) + ".img"
            elif j< 100:
                img_path1 = "image_0" + str(j) + ".img"
            else:
                img_path1 = "image_" + str(j) + ".img"
            
            
            self.filesubtration(filecount, i, dir_path, img_path, img_path1)

            # oldpath = os.path.join(dir_path,"frame")
            # tmppath = os.path.join(dir_path,"frame_tmp")
            # if os.path.exists(oldpath):
            #     os.rename(oldpath, tmppath)

            # oldpath = os.path.join(dir_path,"frame_result")
            # tmppath = os.path.join(dir_path,"frame")
            # if os.path.exists(oldpath):
            #     os.rename(oldpath, tmppath)
        
         
        # filename1 = ""
        # source_dir = os.path.join(dir_path,"frame1")
        # if os.path.exists(source_dir):
        #     file_names = os.listdir(source_dir)
        #     ii = 0
        #     for file_name in file_names:
        #         # shutil.copy(os.path.join(source_dir, file_name), newpath)
        #         if ii < 10:
        #             filename1 = "image_00" + str(ii) + ".img"
        #         elif ii < 100:
        #             filename1 = "image_0" + str(ii) + ".img"
        #         else:
        #             filename1 = "image_" + str(ii) + ".img"
        #         os.rename(os.path.join(source_dir, file_name), os.path.join(source_dir, filename1))
        #         ii = ii + 1

        # shutil.copy(os.path.join(tmppath, "air_0.img"), source_dir)     
        # shutil.copy(os.path.join(tmppath, "dark_0.img"), source_dir)

        # source_dir = os.path.join(dir_path,"frame2")
        # if os.path.exists(source_dir):
        #     file_names = os.listdir(source_dir)
        #     jj = 0
        #     for file_name in file_names:
        #         # shutil.copy(os.path.join(source_dir, file_name), newpath)
        #         if jj < 10:
        #             filename1 = "image_00" + str(jj) + ".img"
        #         elif jj < 100:
        #             filename1 = "image_0" + str(jj) + ".img"
        #         else:
        #             filename1 = "image_" + str(jj) + ".img"
        #         os.rename(os.path.join(source_dir, file_name), os.path.join(source_dir, filename1))
        #         jj = jj + 1

        # shutil.copy(os.path.join(tmppath, "air_0.img"), source_dir)     
        # shutil.copy(os.path.join(tmppath, "dark_0.img"), source_dir)

        # shutil.copy(os.path.join(tmppath, "air_0.img"), newpath)     
        # shutil.copy(os.path.join(tmppath, "dark_0.img"), newpath)
        # shutil.copy(os.path.join(tmppath, "image_000.img"), newpath)
    def converting_mar_files(self, mnri_file_path):
        
        mnri_settings = self.MNRISettings(mnri_file_path)
        dir_path = os.path.dirname(mnri_file_path)
        filecount = int(mnri_settings.value("Frame/FrameCount"))
        frameWidth = int(mnri_settings.value("Frame/FrameWidth"))
        frameHeight = int(mnri_settings.value("Frame/frameHeight"))
        marthreshold = float(mnri_settings.value("Frame/MarThreshold"))
        result_dir11 = os.path.join(dir_path,"framemar")
        if not os.path.exists(result_dir11):
            os.mkdir(result_dir11)
        img_path = ""
        # print(rangeValue)
        for i in range(0, filecount, 1):
            print(i)
            if i < 10:
                img_path = "image_00" + str(i) + ".img"
            elif i< 100:
                img_path = "image_0" + str(i) + ".img"
            else:
                img_path = "image_" + str(i) + ".img"
            img_file_path = os.path.join(dir_path, "frame/" + img_path)
            
            resultfile = np.fromfile(img_file_path, dtype=np.uint16)
            
            
            image = resultfile.reshape(frameWidth, frameHeight)
            image = image.astype(float)
            print(image)
            print(np.max(image))
            
            average1 = self.Average(self.Average(image))
            print(average1)
            if average1 > 3000:
                theta = np.linspace(0., 180., max(image.shape), endpoint=False)
                tmp = radon(image, theta=theta, circle=True)
                print(tmp)
                average = self.Average(self.Average(tmp))
                print(average)
                tmp[ (tmp > average * 5) ] = average * 5

                image[image < (np.max(image) * 0.85)] = 0
                # image1 = image
                # image1[(image1>(np.max(image1) * 0.30)) & (image1 < (np.max(image1) * 0.80))] = 0
                # sinogram[sinogram > 0]=1

                print(tmp)
                reconstruction_fbp = iradon(tmp, theta=theta, circle=True)
                print(reconstruction_fbp)
                
                
                # reconstruction_fbp = reconstruction_fbp  image
                print(reconstruction_fbp)
                reconstruction_fbp = np.array(reconstruction_fbp).ravel()
                image = np.array(reconstruction_fbp).ravel()
                reconstruction_fbp = reconstruction_fbp + image
                print("reconstruction_fbp")
                print(reconstruction_fbp)

                my_array = np.array( reconstruction_fbp , dtype=np.uint16)
                print(my_array)
                my_array.tofile(result_dir11 + "/" + img_path)
        os.rename(dir_path + "/" + "frame" ,dir_path + "/" + "frame_tmp" )
        os.rename(result_dir11,dir_path + "/" + "frame")


    def Average(self,lst): 
        return sum(lst) / len(lst) 
    def reconstruct_odd(self, mnri_file_path, sync=False, cliNode=None, out_path=None):
        """
        Load an MRNI file, create an MHD file for all the projections,
        and run the simplertk filter.
        If no out_path is given, a default path is used (mnri_file_path with -reconstructed.mhd suffix)
        If synchronous, returns once the reconstruction is over, otherwise returns as soon
        as the filter is scheduled.
        A cliNode can be provided to observe cli events
        """
        try:
            mnri_settings = self.MNRISettings(mnri_file_path)
            # typevalues = mnri_settings.value("Frame/Type")
            # if typevalues != 0:
            parameters = self.createCLIParameters1(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
        except:
            parameters = self.createCLIParameters1(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
    def reconstruct_even(self, mnri_file_path, sync=False, cliNode=None, out_path=None):
        """
        Load an MRNI file, create an MHD file for all the projections,
        and run the simplertk filter.
        If no out_path is given, a default path is used (mnri_file_path with -reconstructed.mhd suffix)
        If synchronous, returns once the reconstruction is over, otherwise returns as soon
        as the filter is scheduled.
        A cliNode can be provided to observe cli events
        """
        try:
            mnri_settings = self.MNRISettings(mnri_file_path)
            # typevalues = mnri_settings.value("Frame/Type")
            # if typevalues != 0:
            parameters = self.createCLIParameters2(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
        except:
            parameters = self.createCLIParameters2(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
 
    def reconstruct(self, mnri_file_path, sync=False, cliNode=None, out_path=None):
        """
        Load an MRNI file, create an MHD file for all the projections,
        and run the simplertk filter.
        If no out_path is given, a default path is used (mnri_file_path with -reconstructed.mhd suffix)
        If synchronous, returns once the reconstruction is over, otherwise returns as soon
        as the filter is scheduled.
        A cliNode can be provided to observe cli events
        """
        mnri_settings = self.MNRISettings(mnri_file_path)
        
        dir_path = os.path.dirname(mnri_file_path)
        filecount = int(mnri_settings.value("Frame/FrameCount"))
        # self.converting_files(filecount, dir_path)
        try:
            parameters = self.createCLIParameters(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)
            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
            # elif typevalues == 1:
            #     msg = qt.QMessageBox()
            #     msg.setText(typevalues)
            #     msg.exec_()
            #     self.converting_files(filecount, dir_path)

            #     oldpath = os.path.join(dir_path,"frame")
            #     tmppath = os.path.join(dir_path,"frame_tmp1")
            #     if os.path.exists(oldpath):
            #         os.rename(oldpath, tmppath)
                
            #     oldpath = os.path.join(dir_path,"frame1")
            #     tmppath = os.path.join(dir_path,"frame")
            #     if os.path.exists(oldpath):
            #         os.rename(oldpath, tmppath)

            #     parameters = self.createCLIParameters1(mnri_file_path, out_path)
            #     if cliNode is None:
            #         cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            #     if sync:
            #         cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            #     else:
            #         cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
                
            #     oldpath = os.path.join(dir_path,"frame")
            #     tmppath = os.path.join(dir_path,"frame_tmp2")
            #     if os.path.exists(oldpath):
            #         os.rename(oldpath, tmppath)
                
            #     oldpath = os.path.join(dir_path,"frame2")
            #     tmppath = os.path.join(dir_path,"frame")
            #     if os.path.exists(oldpath):
            #         os.rename(oldpath, tmppath)

                # parameters = self.createCLIParameters2(mnri_file_path, out_path)
                # if cliNode is None:
                #     cliNode = slicer.cli.createNode(slicer.modules.simplertk)

                # if sync:
                #     cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
                # else:
                #     cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
                # return cliNode
        except:
            parameters = self.createCLIParameters(mnri_file_path, out_path)
            if cliNode is None:
                cliNode = slicer.cli.createNode(slicer.modules.simplertk)

            if sync:
                cliNode = slicer.cli.runSync(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            else:
                cliNode = slicer.cli.run(slicer.modules.simplertk, cliNode, parameters, update_display=False)
            return cliNode
class RFReconstructionLogicTestCase(unittest.TestCase):
    def create_mnri_file(self, fileString, outDir):
        output_path = os.path.join(outDir, "test.mnri")
        with open(output_path, "w") as f:
            f.write(fileString)
        return output_path

    def an_mnri_file(self):
        return """
            [Frame]
            ImageFormat=Raw16
            ImageFileExt=img
            PixelDepth=15
            FrameWidth=888
            FrameHeight=1096
            FrameLengthWidth=213.12
            FrameLengthHeight=263.04
            ImageFlipNeed=None
            GainCalibNeed=None
            FrameCount=509
            FrameStart=0
            FrameEnd=508
            FrameFolder=Frame
            FrameBaseName=image_
            FrameNameDigit=3
            DarkFrameName=dark_0
            BrightFrameName=air_0
            """

    def test_an_mnri_file_content_can_be_converted_to_mhd(self):
        logic = RFReconstructionLogic()
        mnri_file_string = self.an_mnri_file()

        expected_mhd_content = """
            ObjectType = Image
            NDims = 3
            DimSize = 888 1096 509
            ElementType = MET_USHORT
            HeaderSize = -1
            ElementSize = 1 1 1
            ElementSpacing = 0.24000 0.24000 1
            ElementByteOrderMSB = False
            ElementDataFile = Frame/image_%03d.img 0 508 1
            """

        tempDir = qt.QTemporaryDir()
        tempDir.setAutoRemove(True)
        file_path = self.create_mnri_file(mnri_file_string, tempDir.path())
        self.assertEqual(logic.stripWhiteSpace(expected_mhd_content), logic.convertMnriToMhd(file_path))

    def test_creating_an_mhd_file_creates_mhd_file_with_the_same_directory_as_mnri_file(self):
        tempDir = qt.QTemporaryDir()
        tempDir.setAutoRemove(True)

        # Create fake mnri file
        mnri_file_string = self.an_mnri_file()
        mnri_file_path = self.create_mnri_file(mnri_file_string, tempDir.path())

        # Create MHD file based on mnri file
        logic = RFReconstructionLogic()
        mhd_file_path = logic.createMhdFile(mnri_file_path)

        # Verify the MHD file was created at the right path
        self.assertTrue(os.path.exists(mhd_file_path))
        self.assertEqual(os.path.dirname(mhd_file_path), tempDir.path())
        self.assertTrue(mhd_file_path.endswith(".mhd"))
        self.assertEqual(os.path.basename(mhd_file_path).replace(".mhd", ""),
                         os.path.basename(mnri_file_path).replace(".mnri", ""))

    def test_after_creation_the_mhd_file_can_be_cleaned_up(self):
        tempDir = qt.QTemporaryDir()
        tempDir.setAutoRemove(True)

        # Create fake mnri file
        mnri_file_string = self.an_mnri_file()
        mnri_file_path = self.create_mnri_file(mnri_file_string, tempDir.path())

        # Create MHD file based on mnri file
        logic = RFReconstructionLogic()
        mhd_file_path = logic.createMhdFile(mnri_file_path)

        # cleanup mhd file and verify it was deleted
        logic.cleanupMhdFile(mhd_file_path)
        self.assertFalse(os.path.exists(mhd_file_path))

    def test_cleaning_not_existing_mhd_file_does_nothing(self):
        logic = RFReconstructionLogic()
        logic.cleanupMhdFile("not_an_existing_path.mhd")


class RFReconstructionTest(ScriptedLoadableModuleTest):
    def runTest(self):
        # Gather tests for the plugin and run them in a test suite
        slicer.mrmlScene.Clear()
        testCases = [RFReconstructionLogicTestCase]
        suite = unittest.TestSuite([unittest.TestLoader().loadTestsFromTestCase(case) for case in testCases])
        unittest.TextTestRunner(verbosity=3).run(suite)
        slicer.mrmlScene.Clear()
