#!/usr/bin/python3

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib
from gi.repository import Gst
#from gi.repository import GObject

import configparser
import os.path
import time
#import signal
import sys

Gst.init(sys.argv)
#signal.signal(signal.SIGINT, signal.SIG_DFL)
#GObject.threads_init()

interval = 5

elements = {
    'pulsesrc':'pulsesrc',
    'rgvolume':'rgvolume',
    'rglimiter':'rglimiter',
    'audioconvert':'audioconvert',
    'tee':'tee',
    'opusenc0':'opusenc',
    'oggmux0':'oggmux',
    'queue0':'queue',
    'filesink':'filesink',
    'opusenc1':'opusenc',
    'oggmux1':'oggmux',
    'queue1':'queue',
    'shout2send':'shout2send',
}

def event_probe2(pad, info, *args):
    Gst.Pad.remove_probe(pad, info.id)
    tee.link(opusenc1)
    opusenc1.set_state(Gst.State.PLAYING)
    oggmux1.set_state(Gst.State.PLAYING)
    queue1.set_state(Gst.State.PLAYING)
    shout2send.set_state(Gst.State.PLAYING)
    return Gst.PadProbeReturn.OK

def reconnect():
    pad = tee.get_static_pad('src_1')
    pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM, event_probe2, None)

def event_probe(pad, info, *args):
    Gst.Pad.remove_probe(pad, info.id)
    tee.unlink(opusenc1)
    opusenc1.set_state(Gst.State.NULL)
    oggmux1.set_state(Gst.State.NULL)
    queue1.set_state(Gst.State.NULL)
    shout2send.set_state(Gst.State.NULL)
    GLib.timeout_add_seconds(interval, reconnect)
    return Gst.PadProbeReturn.OK

def message_handler(bus, message):
    if message.type == Gst.MessageType.ERROR:
        if message.src == shout2send:
            pad = tee.get_static_pad('src_1')
            pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM, event_probe, None)
        else:
            print(message.parse_error())
            pipeline.set_state(Gst.State.NULL)
            exit(1)

def main():
    config = configparser.ConfigParser()
    config.read('libre-streaming.conf')

    pipeline = Gst.Pipeline()
    message_bus = pipeline.get_bus()
    message_bus.add_signal_watch()
    message_bus.connect('message', message_handler)

    for name, kind in elements.items():
        globals()[name] = Gst.ElementFactory.make(kind, name)
        pipeline.add(globals()[name])

    path = os.path.expanduser(config['storage']['path'])

    pulsesrc_caps = Gst.Caps.from_string('audio/x-raw,channels=1')
    rgvolume.set_property('pre-amp', int(config['audio']['micGain'])+6)
    rgvolume.set_property('headroom', int(config['audio']['micGain'])+10)
    opusenc0.set_property('bitrate', int(config['audio']['bitrateLocal'])*1024)
    opusenc1.set_property('bitrate', int(config['audio']['bitrateShout'])*1024)
    filesink.set_property('location', path)
    shout2send.set_property('ip', config['icecast']['ip'])
    shout2send.set_property('port', int(config['icecast']['port']))
    shout2send.set_property('password', config['icecast']['password'])
    shout2send.set_property('mount', config['icecast']['mount'])

    pulsesrc.link_filtered(rgvolume, pulsesrc_caps)
    rgvolume.link(rglimiter)
    rglimiter.link(audioconvert)
    audioconvert.link(tee)

    tee.link(opusenc0)
    opusenc0.link(oggmux0)
    oggmux0.link(queue0)
    queue0.link(filesink)

    tee.link(opusenc1)
    opusenc1.link(oggmux1)
    oggmux1.link(queue1)
    queue1.link(shout2send)

    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.send_event(Gst.Event.new_eos())
        time.sleep(1)
        pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    main()

