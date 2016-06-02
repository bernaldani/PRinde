import logging
import yaml
from apscheduler.jobstores.base import JobLookupError
from core.lib.utils.extended_collections import DotDict
from core.model.ForecastBuilder import ForecastBuilder
from core.modules.config import priority
from core.lib.utils.log import log_format_exception
from core.model.Location import Location
from core.modules.simulations_manager.weather.CombinedSeriesMaker import CombinedSeriesMaker
from core.modules.simulations_manager.weather.HistoricalSeriesMaker import HistoricalSeriesMaker
from core.modules.simulations_manager.weather.NetCDFSeriesMaker import NetCDFSeriesMaker

__author__ = 'Federico Schmidt'


class ForecastLoader:

    def __init__(self, jobs_lock, system_config):
        self.jobs_lock = jobs_lock
        self.system_config = system_config
        self.weather_series_makers = {
            'combined': CombinedSeriesMaker,
            'historic': HistoricalSeriesMaker,
            'netcdf': NetCDFSeriesMaker
        }

    def load_file(self, forecast_file):
        with self.jobs_lock.parallel_job():
            self.__load_file__(forecast_file)

    def reload_file(self, forecast_file, scheduler, forecast_manager):
        with self.jobs_lock.blocking_job(priority=priority.LOAD_FORECAST):
            file_forecasts = self.system_config.forecasts[forecast_file]

            for f in file_forecasts:
                if 'job_id' in f:
                    try:
                        scheduler.remove_job(f['job_id'])
                    except JobLookupError:
                        pass

            if self.__load_file__(forecast_file):
                for f in self.system_config.forecasts[forecast_file]:
                    forecast_manager.schedule_forecast(f)

    def __load_file__(self, forecast_file):
        forecasts = []
        try:
            forecast = DotDict(yaml.safe_load(open(forecast_file)))
            forecast['file_name'] = forecast_file

            weather_series = forecast['configuration']['weather_series']
            if weather_series not in self.weather_series_makers:
                raise RuntimeError('Weather series of type %s not supported.' % weather_series)

            forecast.configuration.weather_maker_class = self.weather_series_makers[weather_series]

            for loc_key in forecast['locations'].keys():
                forecast['locations'][loc_key] = Location(forecast['locations'][loc_key],
                                                          forecast,
                                                          self.system_config)

            builder = ForecastBuilder(forecast, self.system_config)
            builder.replace_aliases(self.system_config.alias_dict)
            builder.inherit_config(self.system_config.system_config_yaml)
            # Build and append forecasts.
            for f in builder.build():
                forecasts.append(f)
                self.system_config.weather_stations_ids.update(
                    set([loc['weather_station'] for loc in f.locations.values()])
                )
            self.system_config.forecasts[forecast_file] = forecasts
            logging.getLogger().info('Loaded %d forecasts from file "%s".' % (len(forecasts), forecast_file))
            return True
        except Exception:
            logging.getLogger().error("Skipping forecast file '%s'. Reason: %s." %
                                      (forecast_file.encode('utf-8'), log_format_exception().encode('utf-8')))
            return False