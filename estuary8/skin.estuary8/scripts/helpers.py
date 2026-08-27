import xbmc
import xbmcvfs
import xbmcgui
import sys
import json

units = [' Bytes', ' kB', ' MB', ' GB', ' TB']


def jsonrpc(query):
    querystring = {"jsonrpc": "2.0", "id": 1}
    querystring.update(query)
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(querystring)))
        if 'result' in response: return response['result']
    except TypeError as e:
        xbmc.log('Error executing JSON RPC: {}'.format(e.args), xbmc.LOGERROR)
    return None


def _copytree(src, dst):
    # xbmcvfs has no recursive copy. Walk the zip:// tree by hand.
    dirs, files = xbmcvfs.listdir(src)
    xbmcvfs.mkdirs(dst)
    for f in files:
        xbmcvfs.copy(src + f, dst + f)
    for d in dirs:
        _copytree('%s%s/' % (src, d), '%s%s/' % (dst, d))


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'toggleAddonStatus':
            '''
                toggles the addon status (enabled/disabled)
                argv[2]: Addon-Id
                argv[3]: Enabled (true/false)
            '''
            result = jsonrpc({"method": "Addons.SetAddonEnabled",
                              "params": {"addonid": sys.argv[2], "enabled": bool(sys.argv[3])}})

        elif sys.argv[1] == "getKodiSetting":
            '''
                get Kodi setting
                [argv2]: setting e.g. "lookandfeel.skin" in guisettings.xml 
            '''
            result = jsonrpc({"method": "Settings.GetSettingValue", "params": {"setting": sys.argv[2]}})
            # jsonrpc() returns None when the response carries no 'result', which
            # is what happens when Home fires this from <onload> before the
            # JSON-RPC service is up. Subscripting it threw on every Kodi start.
            if result is None or 'value' not in result:
                xbmc.log('no value for setting \'%s\', property left unset' % sys.argv[2], xbmc.LOGDEBUG)
            else:
                xbmcgui.Window(10000).setProperty(sys.argv[2], str(result['value']))
                xbmc.log('set Property \'%s\' to %s' % (sys.argv[2], str(result['value'])), xbmc.LOGINFO)

        elif sys.argv[1] == 'getFileSize':
            '''
                get the file size of a file object
                [argv2]: the complete path and filename of the file object, plugin path or network paths (dav/http) are
                excluded by script. Returns formatted file size (e.g. '12.05 GB') in property Window(Home).getProperty(size) 
            '''
            unit = 0
            fs = 0 if (sys.argv[2][0:9] == 'plugin://' or sys.argv[2][0:7] == 'davs://'
                       or sys.argv[2][0:6] == 'dav://' or sys.argv[2][0:7] == 'http://'
                       or sys.argv[2][0:8] == 'https://' or sys.argv[2][0:17] == '/emby_addon_mode/') else xbmcvfs.File(sys.argv[2]).size()
            fs = 0 if fs < 0 else fs

            while fs > 1024 and unit < 5:
                fs /= 1024
                unit += 1
            xbmcgui.Window(10000).setProperty('size', '%s%s' % ('{0:0.2f}'.format(fs), units[unit]))
            xbmc.log('set Property \'size\' to %s%s' % ('{0:0.2f}'.format(fs), units[unit]), xbmc.LOGINFO)

        elif sys.argv[1] == 'calcSeek':
            '''
                calculate the seek position of a time string hh:mm:ss
                [argv2]: time string (hh:)mm:ss. If time string is empty, reset properties seeksec and JumpEnabled
            '''
            try:
                seeksecs = sum(x * int(t) for x, t in zip([1, 60, 3600], reversed(sys.argv[2].split(":")))) + 5 if len(sys.argv[2]) > 0 else 0
                if seeksecs > 0:
                    xbmcgui.Window(10000).setProperty('seeksecs', str(seeksecs * -1))
                    xbmc.log('set Property \'seeksecs\' to ' + str(seeksecs * -1), xbmc.LOGINFO)
                else:
                    xbmcgui.Window(10000).clearProperty('seeksecs')
                    xbmcgui.Window(10000).clearProperty('JumpEnabled')
            except ValueError as e:
                xbmcgui.Window(10000).clearProperty('seeksecs')
                xbmcgui.Window(10000).clearProperty('JumpEnabled')
                xbmc.log(str(e), xbmc.LOGERROR)

        elif sys.argv[1] == 'calculate':
            '''
                calculates two parameters, use integer operations
                [argv2]: operator (add, sub, div, mul)
                [argv3]: first operand (float)
                [argv4]: second operand (float)
                [argv5]: property
                returns result (int) in property Window(Home).getProperty(property)
            '''
            try:

                p1 = float(sys.argv[3])
                p2 = float(sys.argv[4])
                operator = sys.argv[2]
                prop = sys.argv[5]

                if operator == 'add': xbmcgui.Window(10000).setProperty(prop, str(int(p1 + p2)))
                elif operator == 'sub': xbmcgui.Window(10000).setProperty(prop, str(int(p1 - p2)))
                elif operator == 'mul': xbmcgui.Window(10000).setProperty(prop, str(int(p1 * p2)))
                elif operator == 'div': xbmcgui.Window(10000).setProperty(prop, str(int(p1 / p2)))
                else: raise ValueError('Operator unknown')

                xbmc.log('Property \'%s\' calculated' % prop, xbmc.LOGINFO)

            except IndexError:
                xbmc.log('not all parameters provided for math operations', xbmc.LOGERROR)
            except ValueError as e:
                xbmc.log('Value error: %s' % str(e), xbmc.LOGERROR)
        elif sys.argv[1] == 'installRepo':
            '''
                install a repository add-on straight from a static Kodi repo
                [argv2]: the repository add-on id, e.g. repository.tony7bones
                [argv3]: base URL of the static tree holding addons.xml

                Kodi's InstallAddon() builtin can only install something it
                already knows from an INSTALLED repository, so it cannot
                bootstrap the first repo onto a clean box. This does what the
                "install from zip" dialog does, without making the user go
                find the file: resolve the current version from addons.xml so
                the URL cannot go stale, fetch the zip, unpack it into the
                add-ons directory and tell Kodi to rescan.
            '''
            import re as _re
            from urllib.parse import quote
            from urllib.request import urlopen
            addon_id, base = sys.argv[2], sys.argv[3].rstrip('/')
            dlg = xbmcgui.Dialog()
            try:
                # urllib, not xbmcvfs. Kodi's curl VFS returns an empty read for
                # these URLs, measured: 0 chars from a URL curl fetches fine.
                index = urlopen('%s/addons.xml' % base, timeout=30).read().decode('utf-8', 'replace')
                m = _re.search(r'id="%s"[^>]*version="([^"]+)"' % _re.escape(addon_id), index)
                if not m:
                    dlg.notification(addon_id, 'not published at that address')
                    raise SystemExit
                version = m.group(1)
                zipname = '%s-%s.zip' % (addon_id, version)
                url = '%s/%s/%s' % (base, addon_id, zipname)
                blob = urlopen(url, timeout=120).read()
                tmp = xbmcvfs.translatePath('special://temp/%s' % zipname)
                with open(tmp, 'wb') as fh:
                    fh.write(blob)
                # zip:// wants the archive path URL-encoded as one path component
                inner = 'zip://%s/' % quote(tmp, safe='')
                dirs, _files = xbmcvfs.listdir(inner)
                if not dirs:
                    dlg.notification(addon_id, 'zip has no add-on directory')
                    raise SystemExit
                for d in dirs:
                    xbmcvfs.rmdir('special://home/addons/%s' % d, True)
                    _copytree('%s%s/' % (inner, d), 'special://home/addons/%s/' % d)
                xbmcvfs.delete('special://temp/%s' % zipname)
                xbmc.executebuiltin('UpdateLocalAddons')
                xbmc.sleep(2000)
                jsonrpc({"method": "Addons.SetAddonEnabled",
                         "params": {"addonid": addon_id, "enabled": True}})
                dlg.notification(addon_id, 'installed %s' % version)
                xbmc.log('installed %s %s from %s' % (addon_id, version, url), xbmc.LOGINFO)
            except SystemExit:
                pass
            except Exception as e:
                xbmc.log('installRepo failed: %s' % str(e), xbmc.LOGERROR)
                dlg.notification(addon_id, 'install failed, see log')

        else:
            xbmc.log('unknown parameter', xbmc.LOGERROR)

    except IndexError as e:
        xbmc.log(str(e), xbmc.LOGERROR)
