#!/usr/bin/env python3

import prometheus_client as prom
from solaredgeoptimizers import solaredgeoptimizers
from datetime import datetime, timedelta
from requests.exceptions import ConnectionError, ConnectTimeout, Timeout
import argparse
import logging
import json
import time

# local imports
import config

if __name__ == '__main__':
  parser = argparse.ArgumentParser('SolarEdge Inverters Exporter')
  parser.add_argument('-d', '--debug', action='store_true')
  parser.add_argument('-s', '--sleep', type=int, default=60)
  parser.add_argument('-p', '--port', type=int, default=8083)
  args = parser.parse_args()
  if args.debug:
    level=logging.DEBUG
  else:
    level=logging.INFO
  logging.basicConfig(level=level)

  labels = [
    'id',
    'serialnumber',
    'position',
    'model',
    'manufacturer',
    'array',
  ]
  optimizer_power   = prom.Gauge('solaredge_optimizer_power'            , 'Power in Watt', labels, unit='watts')
  optimizer_current = prom.Gauge('solaredge_optimizer_current'          , 'Current in Ampere', labels, unit='ampere')
  optimizer_voltage = prom.Gauge('solaredge_optimizer_voltage'          , 'Voltage in Volt', labels + ['type'], unit='volt')
  optimizer_energy  = prom.Counter('solaredge_optimizer_lifetime_energy', 'Energy in kWh', labels, unit='kwh')
  optimizer_updated = prom.Gauge('solaredge_optimizer_updated'          , 'Time in epoch', labels)
  sensor_updated    = prom.Gauge('updated'                              , 'SolarEdge Optimizers client last updated')
  sensor_up         = prom.Gauge('up'                                   , 'SolarEdge Optimizers client status')
  prom.start_http_server(args.port)

  api = solaredgeoptimizers(siteid=config.siteid, username=config.username, password=config.password)
  while True:
    sensor_up.set(0)
    max_updated = datetime.min
    try:
      site = api.requestListOfAllPanels()
    except (json.decoder.JSONDecodeError, ConnectionError, ConnectTimeout, Timeout) as e:
      logging.warning(f'Caught {type(e).__name__} during requestListOfAllPanels()')
      time.sleep(args.sleep/2)
      continue
    try:
      lifetimeenergy = json.loads(api.getLifeTimeEnergy())
    except (json.decoder.JSONDecodeError, ConnectionError, ConnectTimeout, Timeout) as e:
      logging.warning(f'Caught {type(e).__name__} during getLifeTimeEnergy()')
      lifetimeenergy = None

    for inverter in site.inverters:
      for string in inverter.strings:
        for optimizer in string.optimizers:
          sensor_up.set(1)
          array = config.arrays.get(optimizer.serialNumber, 'unknown')
          if lifetimeenergy:
            lifetime_energy = (float(lifetimeenergy[str(optimizer.optimizerId)]["unscaledEnergy"])) / 1000
          else:
            lifetime_energy = None
          try:
            data = api.requestSystemData(optimizer.optimizerId)
          except Exception as e:
            logging.warning(f'Caught {type(e).__name__}: {str(e)} during requestSystemData({optimizer.optimizerId}) for {optimizer.name} with serial {optimizer.serialNumber}')
            time.sleep(args.sleep/2)
            continue
          labels = {
            'id': optimizer.optimizerId,
            'serialnumber': optimizer.serialNumber,
            'position': optimizer.displayName,
            'model': data.model,
            'manufacturer': data.manufacturer,
            'array': array,
          }
          if datetime.now() - data.lastmeasurement < timedelta(minutes=30):
            optimizer_power.labels(**labels).set(data.power)
            optimizer_current.labels(**labels).set(data.current)
            if lifetime_energy:
              optimizer_energy.labels(**labels)._value.set(lifetime_energy)
            optimizer_updated.labels(**labels).set(time.mktime(data.lastmeasurement.timetuple()))
            labels['type'] = 'Voltage'
            optimizer_voltage.labels(**labels).set(data.voltage)
            labels['type'] = 'Optimizer Voltage'
            optimizer_voltage.labels(**labels).set(data.optimizer_voltage)
          else:
            # measurement is too old: remove actuals
            try:
              optimizer_power.remove(*labels.values())
            except KeyError:
              pass
            try:
              optimizer_current.remove(*labels.values())
            except KeyError:
              pass
            if lifetime_energy:
              optimizer_energy.labels(**labels)._value.set(lifetime_energy)
            optimizer_updated.labels(**labels).set(time.mktime(data.lastmeasurement.timetuple()))
            labels['type'] = 'Voltage'
            try:
              optimizer_voltage.remove(*labels.values())
            except KeyError:
              pass
            labels['type'] = 'Optimizer Voltage'
            try:
              optimizer_voltage.remove(*labels.values())
            except KeyError:
              pass
          if data.lastmeasurement > max_updated:
            max_updated = data.lastmeasurement
            sensor_updated.set(time.mktime(max_updated.timetuple()))

    time.sleep(args.sleep)

