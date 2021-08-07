#!/usr/bin/env python3

import argparse
import logging
import math
import os
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET

import yaml
from mido import MidiFile, MidiTrack, MetaMessage, Message, bpm2tempo

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
LOG = logging.getLogger(__name__)
CFG_HOME = 'configs'
MEDIA_HOME = 'media'
KITS = 'kits'


def main():
    args = _read_args()

    config_file = os.path.join(CFG_HOME, args.config)
    if not os.path.isfile(config_file):
        raise Exception(f"Specified config {args.config} does not exist")
    cfg = yaml.load(open(config_file, 'r'), Loader=yaml.FullLoader)
    kit_name = cfg.get('kit_name')

    if args.create == 'kit':
        LOG.info(f"Creating '{kit_name}' h2drumkit file -- using {config_file}")
        create_kit(cfg)
    else:
        LOG.info(f"Creating '{kit_name}' midi file -- using {config_file}")
        create_midi(cfg)


def create_midi(cfg):
    mid = MidiFile(ticks_per_beat=48)
    track = MidiTrack()
    track.append(MetaMessage('time_signature', numerator=4, denominator=4))
    track.append(MetaMessage('set_tempo', tempo=bpm2tempo(120)))
    mid.tracks.append(track)
    start_offset = 0
    for instrument_idx, instrument in enumerate(cfg.get('instruments', [])):
        name = instrument.get("display")
        LOG.info(f'Writing {name}')
        note = instrument.get('note')
        eigths = math.ceil(instrument.get('length') / 250)
        layers = instrument.get('layers')
        for layer_idx, velocity in enumerate(layers):
            msg = Message('note_on', channel=9, note=note, velocity=velocity, time=start_offset)
            track.append(msg)
            if layer_idx == 0:
                msg = MetaMessage('marker', text=name)
                track.append(msg)
            msg = Message('note_off', channel=9, note=note, time=24)
            track.append(msg)
            start_offset = (eigths - 1) * 24
    msg = Message('note_off', channel=9, note=note, time=(start_offset + 24))
    track.append(msg)
    msg = MetaMessage('marker', text='End')
    track.append(msg)
    midi_file = os.path.join(MEDIA_HOME, cfg.get('kit_code', 'default') + '.mid')
    mid.save(midi_file)


def create_kit(cfg):
    kit_code = cfg.get('kit_code')
    TMP = tempfile.TemporaryDirectory()
    BASE = os.path.join(TMP.name, kit_code)
    os.makedirs(BASE)
    wav_file = os.path.join(MEDIA_HOME, f'{kit_code}.wav')

    # Initializing XML file
    kit = ET.Element('drumkit_info')
    _add_tag(kit, 'name', cfg.get('kit_name', ''))
    _add_tag(kit, 'author', cfg.get('author', ''))
    _add_tag(kit, 'info', cfg.get('info', ''))
    _add_tag(kit, 'license', cfg.get('lincense', ''))

    # Writing Instruments Tag
    instrument_list_xml = ET.SubElement(kit, 'instrumentList')
    instrument_list = cfg.get('instruments')
    start_offset = 0
    defaults = cfg.get('default_attributes', {})

    for idx, instrument in enumerate(instrument_list):
        name = instrument.get('name')
        display = instrument.get('display', name)
        LOG.info(f'Generating data for {display}')

        # Setting XML Stuff
        instrument_xml = ET.SubElement(instrument_list_xml, 'instrument')
        _add_tag(instrument_xml, 'id', str(idx))
        _add_tag(instrument_xml, 'name', display)
        _add_tag(instrument_xml, 'midiOutNote', str(instrument.get('note')))
        instrument_attributes = defaults.copy()
        instrument_attributes.update(instrument.get('attributes', {}))
        _set_instrument_attr(instrument_xml, instrument_attributes)

        # Writing Layers
        layers = instrument.get('layers')
        max_range_values = [f"{(threshold / 127):.6f}" for threshold in layers]
        min_range_values = max_range_values.copy()
        min_range_values.insert(0, "0")
        min_range_values.pop(-1)
        range_values_list = zip(min_range_values, max_range_values)
        sample_length = instrument.get('length')
        note_length = math.ceil(sample_length / 250) * 250

        for idx, range_values in enumerate(range_values_list):
            layer_id = idx + 1

            flac_kit_file = f'{name}_L{layer_id:02}.flac'
            flac_file = os.path.join(BASE, flac_kit_file)

            layer = ET.SubElement(instrument_xml, 'layer')
            _add_tag(layer, 'filename', flac_kit_file)
            _add_tag(layer, 'min', range_values[0])
            _add_tag(layer, 'max', range_values[1])
            _add_tag(layer, 'gain', '1')
            _add_tag(layer, 'pitch', '0')

            start = start_offset + (note_length * idx)
            cmd = [
                "ffmpeg",
                "-loglevel", "quiet",
                "-ss", f"{start / 1000}",
                "-t", f"{sample_length / 1000}",
                "-i", wav_file,
                "-vn",
                "-ac", "1",
                flac_file
            ]
            subprocess.run(cmd)
        start_offset = start_offset + (note_length * len(layers))

    ET.ElementTree(kit).write(os.path.join(BASE, 'drumkit.xml'), xml_declaration=True)
    h2drumkit_file = os.path.join(KITS, f'{kit_code}.h2drumkit')
    if os.path.isfile(h2drumkit_file):
        os.unlink(h2drumkit_file)
    tar = tarfile.open(h2drumkit_file, 'x')
    tar.add(BASE, arcname=kit_code)
    tar.close()


def _set_instrument_attr(instrument, instrument_attributes):
    for attr, value in instrument_attributes.items():
        _add_tag(instrument, attr, str(value))


def _add_tag(element, new_tag_name, value):
    new_tag = ET.SubElement(element, new_tag_name)
    new_tag.text = value
    return


def _read_args():
    description = """
        kit_converter: Generate Hydrogen drumkits by Creating sound samples by other
        plugins
    """
    epilog = """
        More information: https://github.com/pablorocka/hydrogen_drumkit_tools
    """
    arg_parser = argparse.ArgumentParser(description=description, epilog=epilog)
    arg_parser.add_argument(
        "create",
        choices=["midi", "kit"],
        help="Specify whether to generate a midi file or a drumkit file")
    arg_parser.add_argument(
        "-c", "--config",
        help="Specify Yaml file with Kit Configuration (Do Not include configs/ folder)",
        default="default.yml"
    )
    args = arg_parser.parse_args()
    return(args)


def generate_midi():
    LOG.info(f'Generating midi')


if __name__ == "__main__":
    main()
