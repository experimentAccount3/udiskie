import logging
import optparse

import dbus
import gobject
import pynotify

import udiskie.device

class DeviceState:
    def __init__(self, mounted, has_media):
        self.mounted = mounted
        self.has_media = has_media


class AutoMounter:
    def __init__(self, bus=None):
        self.log = logging.getLogger('udiskie.mount.AutoMounter')
        self.last_device_state = {}

        if not bus:
            from dbus.mainloop.glib import DBusGMainLoop
            DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
        else:
            self.bus = bus

        self.bus.add_signal_receiver(self.device_added,
                                     signal_name='DeviceAdded',
                                     bus_name='org.freedesktop.UDisks')
        self.bus.add_signal_receiver(self.device_removed,
                                     signal_name='DeviceRemoved',
                                     bus_name='org.freedesktop.UDisks')
        self.bus.add_signal_receiver(self.device_changed,
                                     signal_name='DeviceChanged',
                                     bus_name='org.freedesktop.UDisks')

    def _mount_device(self, device):
        if device.is_handleable() and not device.is_mounted():
            filesystem = str(device.id_type())
            options = []
            try:
                device.mount(filesystem, options)
                self.log.info('mounted device %s' % (device,))
            except dbus.exceptions.DBusException, dbus_err:
                self.log.error('failed to mount device %s: %s' % (device,
                                                                  dbus_err))
                return

            mount_paths = ', '.join(device.mount_paths())
            pynotify.Notification('Device mounted',
                                  '%s mounted on %s' % (device.device_file(),
                                                        mount_paths),
                                  'drive-removable-media').show()

        self._store_device_state(device)

    def _store_device_state(self, device):
        state = DeviceState(device.is_mounted(),
                            device.has_media())
        self.last_device_state[device.device_path] = state

    def _remove_device_state(self, device):
        if device.device_path in self.last_device_state:
            del self.last_device_state[device.device_path]

    def _get_device_state(self, device):
        return self.last_device_state.get(device.device_path)

    def mount_present_devices(self):
        """Mount handleable devices that are already present."""
        for device in udiskie.device.get_all(self.bus):
            self._mount_device(device)

    def device_added(self, device):
        self.log.debug('device added: %s' % (device,))
        udiskie_device = udiskie.device.Device(self.bus, device)
        # Since the device just appeared we don't want the old state.
        self._remove_device_state(udiskie_device)
        self._mount_device(udiskie_device)

    def device_removed(self, device):
        self.log.debug('device removed: %s' % (device,))
        self._remove_device_state(udiskie.device.Device(self.bus, device))

    def device_changed(self, device):
        self.log.debug('device changed: %s' % (device,))

        udiskie_device = udiskie.device.Device(self.bus, device)
        last_state = self._get_device_state(udiskie_device)

        if not last_state:
            # First time we saw the device, try to mount it.
            self._mount_device(udiskie_device)
        else:
            media_added = False
            if udiskie_device.has_media() and not last_state.has_media:
                media_added = True

            if media_added and not last_state.mounted:
                # Wasn't mounted before, but it has new media now.
                self._mount_device(udiskie_device)

        self._store_device_state(udiskie_device)


def cli(args):
    parser = optparse.OptionParser()
    parser.add_option('-v', '--verbose', action='store_true',
                      dest='verbose', default=False,
                      help='verbose output')
    (options, args) = parser.parse_args(args)

    log_level = logging.INFO
    if options.verbose:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format='%(message)s')

    pynotify.init('udiskie.mount')

    mounter = AutoMounter()
    mounter.mount_present_devices()
    return gobject.MainLoop().run()
