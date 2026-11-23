# SPDX-License-Identifier: MIT
"""Arto Sensei: a Krita docker that teaches Krita and the feel of digital painting.

Part of Seriously Open Games. Code MIT, lesson content CC BY 4.0, Oscar Baechler.
"""
from krita import Krita, DockWidgetFactory, DockWidgetFactoryBase

from .docker import ArtoSenseiDocker

Krita.instance().addDockWidgetFactory(
    DockWidgetFactory("arto_sensei", DockWidgetFactoryBase.DockRight, ArtoSenseiDocker))
