import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
)
from constructs import Construct


class InfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        account = self.account
        region  = self.region

        # ── VPC ──────────────────────────────────────────────────────────────
        vpc = ec2.Vpc(self, "AppVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                )
            ]
        )

        # ── ECS Cluster ───────────────────────────────────────────────────────
        cluster = ecs.Cluster(self, "AppCluster", vpc=vpc)

        # ── ECR image references ──────────────────────────────────────────────
        api1_image = ecs.ContainerImage.from_ecr_repository(
            ecr.Repository.from_repository_name(self, "Api1Repo", "api1"),
            tag="latest"
        )
        api2_image = ecs.ContainerImage.from_ecr_repository(
            ecr.Repository.from_repository_name(self, "Api2Repo", "api2"),
            tag="latest"
        )

        # ── Security Group for ECS tasks ──────────────────────────────────────
        ecs_sg = ec2.SecurityGroup(self, "EcsSG",
            vpc=vpc,
            description="Allow ALB to reach ECS tasks",
            allow_all_outbound=True
        )

        # ── ALB ───────────────────────────────────────────────────────────────
        alb_sg = ec2.SecurityGroup(self, "AlbSG",
            vpc=vpc,
            description="Allow HTTP from internet",
            allow_all_outbound=True
        )
        alb_sg.add_ingress_rule(ec2.Peer.prefix_list("pl-82a045eb"), ec2.Port.tcp(80), "CloudFront only")

        # Allow ALB SG to reach ECS tasks on port 5000 and 6001
        ecs_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(5000), "ALB to API1")
        ecs_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(6001), "ALB to API2")

        alb = elbv2.ApplicationLoadBalancer(self, "AppALB",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        )

        listener = alb.add_listener("HttpListener",
            port=80,
            default_action=elbv2.ListenerAction.fixed_response(
                404, content_type="text/plain", message_body="Not Found"
            )
        )

        # ── Task Execution Role ───────────────────────────────────────────────
        exec_role = iam.Role(self, "EcsExecRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ]
        )

        # ── API1 Task + Service ───────────────────────────────────────────────
        api1_task = ecs.FargateTaskDefinition(self, "Api1Task",
            cpu=256,
            memory_limit_mib=512,
            execution_role=exec_role
        )
        api1_task.add_container("Api1Container",
            image=api1_image,
            port_mappings=[ecs.PortMapping(container_port=5000)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api1")
        )

        api1_service = ecs.FargateService(self, "Api1Service",
            cluster=cluster,
            task_definition=api1_task,
            desired_count=1,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True
        )

        # ── API2 Task + Service ───────────────────────────────────────────────
        api2_task = ecs.FargateTaskDefinition(self, "Api2Task",
            cpu=256,
            memory_limit_mib=512,
            execution_role=exec_role
        )
        api2_task.add_container("Api2Container",
            image=api2_image,
            port_mappings=[ecs.PortMapping(container_port=6001)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api2")
        )

        api2_service = ecs.FargateService(self, "Api2Service",
            cluster=cluster,
            task_definition=api2_task,
            desired_count=1,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True
        )

        # ── Target Groups + Listener Rules ────────────────────────────────────
        tg1 = elbv2.ApplicationTargetGroup(self, "TG1",
            vpc=vpc,
            port=5000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/api1")
        )
        api1_service.attach_to_application_target_group(tg1)

        tg2 = elbv2.ApplicationTargetGroup(self, "TG2",
            vpc=vpc,
            port=6001,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/api2")
        )
        api2_service.attach_to_application_target_group(tg2)

        listener.add_action("Api1Rule",
            priority=1,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api1*"])],
            action=elbv2.ListenerAction.forward([tg1])
        )

        listener.add_action("Api2Rule",
            priority=2,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api2*"])],
            action=elbv2.ListenerAction.forward([tg2])
        )

        # ── S3 Bucket ─────────────────────────────────────────────────────────
        bucket = s3.Bucket(self, "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # ── CloudFront Distribution ───────────────────────────────────────────
        distribution = cloudfront.Distribution(self, "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket)
            ),
            default_root_object="index.html"
        )
                # ── ALB Origin for CloudFront ─────────────────────────────────────────
        alb_origin = origins.HttpOrigin(alb.load_balancer_dns_name,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY
        )

        distribution.add_behavior("/api1*",
            origin=alb_origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER
        )

        distribution.add_behavior("/api2*",
            origin=alb_origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER
        )

        # ── Upload index.html to S3 ───────────────────────────────────────────
        s3deploy.BucketDeployment(self, "DeployFrontend",
            sources=[s3deploy.Source.asset("../frontend")],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"]
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "ALBDnsName",
            value=alb.load_balancer_dns_name,
            description="ALB DNS — use this to test your APIs"
        )

        CfnOutput(self, "CloudFrontURL",
            value=f"https://{distribution.distribution_domain_name}",
            description="Frontend URL"
        )