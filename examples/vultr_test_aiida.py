#!/usr/bin/env python3
"""Submit MgO single-point CRYSTAL calculation via AiiDA to yascheduler (Vultr).

Usage:
    export MPDS_KEY=...
    python examples/vultr_test_aiida.py
"""

import os
import sys

from aiida import load_profile
from aiida.engine import submit
from aiida.plugins import DataFactory
from mpds_aiida.workflows.crystal_mpds import MPDSStructureWorkChain
from mpds_aiida.common import get_template

load_profile()

formula = sys.argv[1] if len(sys.argv) > 1 else "MgO"
sgs = int(sys.argv[2]) if len(sys.argv) > 2 else 225

workchain_options = get_template("nonmetallic.yml")
workchain_options["options"]["need_phonons"] = False
workchain_options["options"]["need_elastic_constants"] = False
workchain_options["options"]["need_properties"] = False
workchain_options["options"]["is_magnetic"] = False

inputs = MPDSStructureWorkChain.get_builder()
inputs.workchain_options = DataFactory("dict")(dict=workchain_options)
inputs.mpds_query = DataFactory("dict")(dict={"formulae": formula, "sgs": sgs})
inputs.metadata.label = f"{formula}/{sgs} vultr test"

calc = submit(MPDSStructureWorkChain, **inputs)
print(f"Submitted MPDSStructureWorkChain for {formula}/{sgs} → PK={calc.pk}")
