import qt
import slicer

from RFViewerHomeLib import wrapInCollapsibleButton


class ModuleWidget(qt.QWidget):
    """Simple widget enabling swapping one module for another in the same layout"""

    def __init__(self):
        qt.QStackedWidget.__init__(self)
        self._previousModule = None

        layout = qt.QVBoxLayout(self)
        self._stackWidget = qt.QStackedWidget()
        self._collapsibleButton = wrapInCollapsibleButton(self._stackWidget, "")
        layout.addWidget(self._collapsibleButton)
        layout.setMargin(0)
        self._collapsibleButton.visible = False
        self._moduleSelector = slicer.util.mainWindow().moduleSelector()

    def setModule(self, moduleWidget, moduleName):
        self._moduleSelector.selectModule('RFViewerHome')
        if self._previousModule is not None:
            self._previousModule.exit()
            self._stackWidget.removeWidget(self._previousModule)

        self._collapsibleButton.visible = True
        self._collapsibleButton.text = moduleName
        self._collapsibleButton.collapsed = False
        self._stackWidget.addWidget(moduleWidget)
        self._previousModule = moduleWidget

        moduleWidget.enter()


class ToolbarWidget(qt.QWidget):
    """Widget for creating and arranging toolbar buttons"""

    def __init__(self):
        qt.QWidget.__init__(self)
        self._sectionLayout = None
        self._layout = qt.QVBoxLayout()
        # self._layout.setSpacing(10)
        self.setLayout(self._layout)

    def _hasPreviousSection(self):
        return self._sectionLayout is not None

    def createSection(self, sectionName=""):
        self.closeLastSection()
        self._sectionLayout = qt.QHBoxLayout()

        if sectionName:
            self._addSectionName(sectionName)

    def closeLastSection(self):
        if self._hasPreviousSection():
            self._sectionLayout.addStretch()
            self._layout.addLayout(self._sectionLayout)
            self._addSeparator()

    def addButton(self, button):
        self._sectionLayout.addWidget(button)

    def _addSeparator(self):
        separator = qt.QFrame()
        separator.setFrameShape(qt.QFrame.HLine)
        separator.setFrameShadow(qt.QFrame.Sunken)
        separator.setStyleSheet("background-color: grey;")
        self._layout.addWidget(separator)

    def _addSectionName(self, sectionName):
        self._layout.addWidget(qt.QLabel(sectionName))
