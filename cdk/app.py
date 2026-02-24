#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.infra_stack import InfraStack

app = cdk.App()

InfraStack(app, "InfraStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region="us-west-2"
    )
)

app.synth()