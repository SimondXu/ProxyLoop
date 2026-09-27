#!/usr/bin/env bash
# S1-SYS-13 PLANT: a deliberate shellcheck error (SC2086) so CI must fail. To be reverted.
if [ $1 = "x" ]; then
  echo "planted"
fi
