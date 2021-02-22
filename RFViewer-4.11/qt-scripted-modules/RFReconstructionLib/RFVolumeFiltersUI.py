import qt, ctk

from RFViewerHomeLib import translatable
from RFVisualizationLib import truncate


@translatable
class RFVolumeFiltersUI(qt.QWidget):
  def __init__(self):
    qt.QWidget.__init__(self)

    self.volumeFilterLayout = qt.QFormLayout()
    self.volumeFilterLayout.setMargin(10)
    self.volumeFilterLayout.setVerticalSpacing(10)

    layoutMedian, self.medianButton, self.medianSlider = self.createVolumeFilterUIWithSlider(defaultSliderValue=1, sliderStep=1, sliderTooltip=self.tr('Kernel size'))
    self.volumeFilterLayout.addRow(self.tr("Denoise:"), layoutMedian)

    layoutGaussian, self.gaussianButton, self.gaussianSlider = self.createVolumeFilterUIWithSlider(defaultSliderValue=0.2, sliderStep=0.1, sliderTooltip=self.tr('Gaussian variance'))
    self.volumeFilterLayout.addRow(self.tr("Smooth:"), layoutGaussian)

    layoutSharpening = self.createSharpeningFilterUI()
    self.volumeFilterLayout.addRow(self.tr("Sharpen:"), layoutSharpening)

    self.setLayout(self.volumeFilterLayout)

  def createVolumeFilterUIWithSlider(self, defaultSliderValue, sliderStep, sliderTooltip):
    """
    Create a layout with a button, a slider and a label which displays the slider value
    return a layout, the button, the slider and the label
    """
    button = qt.QPushButton(self.tr('Apply'))

    slider = ctk.ctkDoubleSlider()
    slider.setValue(defaultSliderValue)
    slider.singleStep = sliderStep
    slider.pageStep = 1
    slider.maximum = 100
    slider.setToolTip(sliderTooltip)
    slider.setOrientation(qt.Qt.Horizontal)

    label = qt.QLabel()
    label.text = defaultSliderValue

    def callbackInt():
      label.text = int(slider.value)
    def callbackFloat():
      label.text = truncate(slider.value, 1)
    slider.connect("valueChanged(double)", callbackInt if type(sliderStep) is int else callbackFloat)

    layout = qt.QHBoxLayout()
    layout.addWidget(slider)
    layout.addWidget(label)
    layout.addWidget(button)
    layout.setSpacing(5)

    return layout, button, slider

  def createSharpeningFilterUI(self):
    layout = qt.QHBoxLayout()

    self.sharpenButton = qt.QPushButton(self.tr('Apply'))

    layout.addStretch(1)
    layout.addWidget(self.sharpenButton)
    layout.setSpacing(5)

    return layout
