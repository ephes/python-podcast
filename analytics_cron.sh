#!/bin/bash

cd $HOME/python-podcast
(env $(cat .analytics_env | xargs) /home/python-podcast/.virtualenvs/pp/bin/python manage.py access_log_import 2>&1) > access_log_import.log
