#!/bin/bash

# iterate through all the files in the directory that match conf.d_* and copy them to the respective /etc/httpd/conf.d/* directory

for file in $(ls /secret_configs/conf.d_*); do
  regex="conf.d_(.*)_(.*\.yaml)"
  [[ $file =~ $regex ]]

  dir="/etc/datadog-agent/conf.d/${BASH_REMATCH[1]}"
  mkdir -p "${dir}"
  cp $file "${dir}/${BASH_REMATCH[2]}"
done