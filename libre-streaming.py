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

class LibreStreaming:
    def __init__(self, config):
        micGain = int(config['audio']['micGain'])
        bitrateLocal = int(config['audio']['bitrateLocal'])
        bitrateShout = int(config['audio']['bitrateShout'])
        path = os.path.expanduser(config['storage']['path'])
        icecast = dict(config['icecast'])
        icecast['port'] = int(icecast['port'])

        elements = [
            ['pulsesrc', {}],
            ['rgvolume', {'pre-amp':micGain+6, 'headroom':micGain+10}],
            ['rglimiter', {}],
            ['audioconvert', {}],
            ['tee', {}],
            # tee src_0
            ['opusenc', {'bitrate':bitrateLocal*1024}],
            ['oggmux', {}],
            ['queue', {}],
            ['filesink', {'location':path}],
            # tee src_1
            ['opusenc', {'bitrate':bitrateShout*1024}],
            ['oggmux', {}],
            ['queue', {}],
            ['shout2send', icecast],
        ]

        self.pipeline = Gst.Pipeline()
        message_bus = self.pipeline.get_bus()
        message_bus.add_signal_watch()
        message_bus.connect('message', self.messageHandler)

        for kind, attrs in elements:
            i = sum(map(lambda v: v.startswith(kind), vars(self)))
            name = kind+str(i)
            vars(self)[name] = Gst.ElementFactory.make(kind, name)
            for key, value in attrs.items():
                vars(self)[name].set_property(key, value)
            self.pipeline.add(vars(self)[name])

        # Linking
        pulsesrc0_caps = Gst.Caps.from_string('audio/x-raw,channels=1')
        self.pulsesrc0.link_filtered(self.rgvolume0, pulsesrc0_caps)
        self.subpipelines = [
            [self.rgvolume0, self.rglimiter0,
                self.audioconvert0, self.tee0],
            [self.tee0, self.opusenc0, self.oggmux0,
                self.queue0, self.filesink0],
            [self.tee0, self.opusenc1, self.oggmux1,
                self.queue1, self.shout2send0],
        ]
        for subpipeline in self.subpipelines:
            for prev, next in zip(subpipeline, subpipeline[1:]):
                prev.link(next)

    def setState(self, state, *elements):
        for element in elements:
            element.set_state(state)

    def shout2sendReconnect(self, pad, info):
        Gst.Pad.remove_probe(pad, info.id)
        self.tee0.link(self.opusenc1)
        self.setState(Gst.State.PLAYING, *self.subpipelines[2][1:])
        return Gst.PadProbeReturn.OK

    def shout2sendPreReconnect(self):
        pad = self.tee0.get_static_pad('src_1')
        pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM, 
                      self.shout2sendReconnect)

    def shout2sendDown(self, pad, info):
        Gst.Pad.remove_probe(pad, info.id)
        self.tee0.unlink(self.opusenc1)
        self.setState(Gst.State.NULL, *self.subpipelines[2][1:])
        GLib.timeout_add_seconds(interval, self.shout2sendPreReconnect)
        return Gst.PadProbeReturn.OK

    def messageHandler(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            if message.src == self.shout2send0:
                pad = self.tee0.get_static_pad('src_1')
                pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM,
                               self.shout2sendDown)
            else:
                print(message.parse_error())
                self.pipeline.set_state(Gst.State.NULL)
                exit(1)

    def play(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.pipeline.send_event(Gst.Event.new_eos())
            time.sleep(1)
            self.pipeline.set_state(Gst.State.NULL)

def main(filename='libre-streaming.conf'):
    config = configparser.ConfigParser()
    if not config.read(filename):
        print("Unable to read {0!s}".format(filename))
        exit(1)
    libreStreaming = LibreStreaming(config)
    libreStreaming.play()

if __name__ == '__main__':
    main()

