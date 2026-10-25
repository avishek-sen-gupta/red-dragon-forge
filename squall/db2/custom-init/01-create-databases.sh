#!/bin/bash
# IBM db2_community image runs scripts in /var/custom once, after instance setup.
# DBNAME=MOJO already created the first database; create MOJO2 here if absent.
# Tests self-provision their own tables, so no schema seeding.
set -euo pipefail

create_db_if_absent() {
  local db="$1"
  if su - db2inst1 -c "db2 list db directory" | grep -q "Database alias *= ${db}$"; then
    echo "custom-init: ${db} already exists, skipping"
  else
    echo "custom-init: creating ${db}"
    su - db2inst1 -c "db2 create database ${db}"
  fi
}

su - db2inst1 -c "db2start" || true   # ensure the manager is up before CREATE
create_db_if_absent MOJO
create_db_if_absent MOJO2
su - db2inst1 -c "db2 update dbm cfg using INSTANCE_MEMORY 524288"
echo "custom-init: databases ready, instance memory capped at 2 GiB"
