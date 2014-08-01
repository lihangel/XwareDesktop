# -*- coding: utf-8 -*-

import logging
from launcher import app

from PyQt5.QtCore import QObject, pyqtSlot, QMetaType, QUrl
from PyQt5.QtDBus import QDBusConnection, QDBusInterface, QDBusArgument, QDBusMessage
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtMultimedia import QSound

import os

_DBUS_NOTIFY_SERVICE = "org.freedesktop.Notifications"
_DBUS_NOTIFY_PATH = "/org/freedesktop/Notifications"
_DBUS_NOTIFY_INTERFACE = "org.freedesktop.Notifications"


class Notifier(QObject):
    _conn = None
    _interface = None
    _notifications = None  # a dict of notifyId: taskDict
    _capabilities = None
    _completedTasksStat = None

    def __init__(self, parent):
        super().__init__(parent)
        self._conn = QDBusConnection("Xware Desktop").sessionBus()

        self._interface = QDBusInterface(_DBUS_NOTIFY_SERVICE,
                                         _DBUS_NOTIFY_PATH,
                                         _DBUS_NOTIFY_INTERFACE,
                                         self._conn)

        self._notifications = {}
        self._completedTasksStat = app.etmpy.completedTasksStat
        self._completedTasksStat.sigTaskCompleted.connect(self.notifyTask)

        self._capabilities = self._getCapabilities()
        if "actions" in self._capabilities:
            successful = self._conn.connect(_DBUS_NOTIFY_SERVICE,
                                            _DBUS_NOTIFY_PATH,
                                            _DBUS_NOTIFY_INTERFACE,
                                            "ActionInvoked", self.slotActionInvoked)
            if not successful:
                logging.error("ActionInvoked connect failed.")

        self._qSound_complete = QSound(":/sound/download-complete.wav", self)

    @property
    def isConnected(self):
        return self._conn.isConnected()

    def notifyTask(self, taskId):
        task = self._completedTasksStat.getTask(taskId)

        if task.get("state", None) == 11:  # see definitions in class TaskStatistic.
            if app.settings.getbool("frontend", "notifybysound"):
                self._qSound_complete.play()
            self._dbus_notify(task)
        else:
            # TODO: Also notify if errors occur
            pass

    def _getCapabilities(self):
        # get libnotify server caps and remember it.
        qdBusMsg = self._interface.call(
            "GetCapabilities"
        )
        if qdBusMsg.errorName():
            logging.error("cannot get org.freedesktop.Notifications.GetCapabilities")
            return []
        else:
            return qdBusMsg.arguments()[0]

    def _dbus_notify(self, task):
        if not app.settings.getbool("frontend", "popnotifications"):
            return

        if "actions" in self._capabilities:
            actions = QDBusArgument(["open", "打开", "openDir", "打开文件夹"], QMetaType.QStringList)
        else:
            actions = QDBusArgument([], QMetaType.QStringList)

        qdBusMsg = self._interface.call(
            "Notify",
            QDBusArgument("Xware Desktop", QMetaType.QString),  # app_name
            QDBusArgument(0, QMetaType.UInt),  # replace_id
            QDBusArgument("xware-desktop", QMetaType.QString),  # app_icon
            QDBusArgument("下载完成", QMetaType.QString),  # summary
            QDBusArgument(task["name"], QMetaType.QString),  # body
            actions,
            {
                "category": "transfer.complete",
            },  # hints
            QDBusArgument(5000, QMetaType.Int),  # timeout
        )

        if qdBusMsg.errorName():
            logging.error("DBus, notifyTask {}: {}".format(qdBusMsg.errorName(),
                                                           qdBusMsg.errorMessage()))
        else:
            # add it to the dict
            self._notifications[qdBusMsg.arguments()[0]] = task

    @pyqtSlot(QDBusMessage)
    def slotActionInvoked(self, msg):
        notifyId, action = msg.arguments()
        task = self._notifications.get(notifyId, None)
        if not task:
            # other applications' notifications
            return
        name = task["name"]  # filename
        path = task["path"]  # location

        if action == "open":
            openPath = os.path.join(path, name)
        elif action == "openDir":
            openPath = path
        elif action == "default":  # Unity's notify osd always have a default action.
            return
        else:
            raise Exception("Unknown action from slotActionInvoked: {}.".format(action))

        localOpenPath = app.mountsFaker.convertToLocalPath(openPath)
        qUrl = QUrl.fromLocalFile(localOpenPath)
        QDesktopServices().openUrl(qUrl)
