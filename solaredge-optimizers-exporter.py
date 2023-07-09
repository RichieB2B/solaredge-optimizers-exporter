#!/usr/bin/env python3

import prometheus_client as prom
from solaredgeoptimizers import solaredgeoptimizers
from datetime import datetime, timedelta
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
  optimizer_energy  = prom.Counter('solaredge_optimizer_lifetime_energy', 'Energy in kWh', labels, unit='kWh')
  optimizer_updated = prom.Gauge('solaredge_optimizer_updated'          , 'Time in epoch', labels)
  sensor_updated    = prom.Gauge('updated'                              , 'SolarEdge Optimizers client last updated')
  sensor_up         = prom.Gauge('up'                                   , 'SolarEdge Optimizers client status')
  prom.start_http_server(args.port)

  api = solaredgeoptimizers(siteid=config.siteid, username=config.username, password=config.password)
  while True:
    up = 0
    max_updated = datetime.min
    site = api.requestListOfAllPanels()
    lifetimeenergy = json.loads(api.getLifeTimeEnergy())
    for inverter in site.inverters:
      for string in inverter.strings:
        for optimizer in string.optimizers:
          up = 1
          array = config.arrays.get(optimizer.serialNumber, 'unknown')
          lifetime_energy = (float(lifetimeenergy[str(optimizer.optimizerId)]["unscaledEnergy"])) / 1000
          data = api.requestSystemData(optimizer.optimizerId)
          labels = {
            'id': optimizer.optimizerId,
            'serialnumber': optimizer.serialNumber,
            'position': optimizer.displayName,
            'model': data.model,
            'manufacturer': data.manufacturer,
            'array': array,
          }
          if datetime.now() - data.lastmeasurement < timedelta(minutes=10):
            optimizer_power.labels(**labels).set(data.power)
            optimizer_current.labels(**labels).set(data.current)
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
    sensor_up.set(up)

    time.sleep(args.sleep)

