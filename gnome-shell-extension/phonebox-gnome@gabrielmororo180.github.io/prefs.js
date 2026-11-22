import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gio from 'gi://Gio';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class PhoneBoxPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: 'PhoneBox agent',
            description: 'The agent listens on 127.0.0.1. Change the port only if the agent was started with --port.',
        });

        // Adw.SpinRow needs libadwaita 1.4; GNOME 45 ships it
        const port = new Adw.SpinRow({
            title: 'Port',
            adjustment: new Gtk.Adjustment({lower: 1024, upper: 65535, step_increment: 1, page_increment: 10}),
        });
        settings.bind('port', port, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(port);

        page.add(group);
        window.add(page);
    }
}
