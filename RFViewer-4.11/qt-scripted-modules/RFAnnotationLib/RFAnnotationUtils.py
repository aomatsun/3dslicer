import slicer, vtk

def getOrCreateTableColumn(outputTable, arrayName):
  """
  Get a vtk array from a table
  """
  distanceArray = outputTable.GetTable().GetColumnByName(arrayName)
  if distanceArray:
    return distanceArray
  newArray = vtk.vtkDoubleArray()
  newArray.SetName(arrayName)
  outputTable.GetTable().AddColumn(newArray)
  return newArray

def getLineResolutionFromLineLength(lineLengthInMM):
  """
  Define plot resolution according to the line length
  We define 10 points per mm
  """
  return lineLengthInMM * 10

def getCurrentLayout():
  """
  Return the current SlicerLayout (cf vtkMRMLLayoutNode)
  """
  return slicer.app.layoutManager().layout