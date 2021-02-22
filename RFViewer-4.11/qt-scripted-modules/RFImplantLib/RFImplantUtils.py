from enum import unique, IntEnum

import qt

@unique
class Roles(IntEnum):
    id = qt.Qt.UserRole
    company = qt.Qt.UserRole + 1
    model = qt.Qt.UserRole + 2
    diameter = qt.Qt.UserRole + 3
    length = qt.Qt.UserRole + 4
    file = qt.Qt.UserRole + 5

