#!/bin/sh
# Download the MyConnectome scans the pipeline uses (~900 MB) from OpenNeuro ds000031 into data/.
set -e
B="https://s3.amazonaws.com/openneuro.org/ds000031/sub-01"
mkdir -p data && cd data
for f in \
  ses-2022/anat/sub-01_ses-2022_T1w.nii.gz ses-2022/anat/sub-01_ses-2022_T1w.json \
  ses-2015/dwi/sub-01_ses-2015_acq-g79_dir-pe0_dwi.nii.gz ses-2015/dwi/sub-01_ses-2015_acq-g79_dir-pe0_dwi.bval \
  ses-2015/dwi/sub-01_ses-2015_acq-g79_dir-pe0_dwi.bvec ses-2015/dwi/sub-01_ses-2015_acq-g79_dir-pe0_dwi.json; do
  [ -f "$(basename $f)" ] || curl -sfo "$(basename $f)" "$B/$f"
done
