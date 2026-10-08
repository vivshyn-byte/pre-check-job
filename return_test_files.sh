#!/bin/bash

# This script copies few JSON files from the 'processed' directory in the GCS bucket to the 'reports' directory.

gcloud storage cp 'gs://reports_to_check/processed/81*.json' gs://reports_to_check/reports/
gcloud storage cp 'gs://reports_to_check/processed/FEB79894A8AB4439B5B8.json' gs://reports_to_check/reports/ #bad image

