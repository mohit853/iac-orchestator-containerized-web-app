# ECS Fargate Multi Container API Architecture

## High Level Design

```mermaid
%%{init: {'theme':'base', 'themeVariables': {
'primaryColor': '#e3f2fd',
'primaryBorderColor': '#1e88e5',
'lineColor': '#546e7a',
'secondaryColor': '#fce4ec',
'tertiaryColor': '#f3e5f5',
'fontSize': '14px'
}}}%%
flowchart LR
User[User Browser]
DNS[Route 53]
subgraph VPC
    IGW[Internet Gateway]
    subgraph Public Subnet
        ALB[Application Load Balancer :80]
    end
    subgraph Private Subnet
        subgraph ECS Task
            ENI[Task Private IP]
            API1[API1 Container :5000]
            API2[API2 Container :6000]
        end
    end
end
TG1[API1 Target Group]
TG2[API2 Target Group]
User --> DNS
DNS --> ALB
ALB -->|/api1| TG1
ALB -->|/api2| TG2
TG1 --> ENI
TG2 --> ENI
ENI --> API1
ENI --> API2
```

---

## Architecture Overview

This project implements a containerized backend application deployed on AWS using ECS Fargate behind an Application Load Balancer. The frontend interacts with backend APIs through a public endpoint exposed securely using AWS networking components.

User requests are first resolved through Route 53 which maps the application domain name to the public endpoint of the Application Load Balancer. The load balancer is deployed within a public subnet of a Virtual Private Cloud and acts as the entry point for all incoming internet traffic.

Based on path based routing rules the load balancer forwards incoming requests to the appropriate target group. Each target group corresponds to a specific backend API running inside containers that are deployed as part of an ECS Fargate task within a private subnet.

The ECS task hosts multiple containers each responsible for handling a separate API endpoint. These containers share a common task level network interface with a private IP address enabling secure internal communication while remaining inaccessible directly from the internet.

Security groups are configured to allow public traffic to reach the load balancer while restricting backend container access to only the load balancer ensuring that application services remain private and protected within the VPC.

This architecture enables secure exposure of backend services to external clients while maintaining network isolation for internal application components.

---

## Low Level Design

```mermaid
%%{init: {'theme':'base', 'themeVariables': {
'primaryColor': '#e3f2fd',
'primaryBorderColor': '#1e88e5',
'lineColor': '#546e7a',
'secondaryColor': '#fce4ec',
'tertiaryColor': '#f3e5f5',
'fontSize': '14px'
}}}%%
flowchart TD

    Stack["Stack\nCDK Base Class"]

    subgraph InfraStack["InfraStack extends Stack"]

        Vpc["Vpc\nmax_azs: 2\nnat_gateways: 0\nsubnet: PUBLIC"]

        subgraph SGLayer["Security Groups"]
            ALBSG["SecurityGroup\nalb_sg\nInbound: TCP 80 from 0.0.0.0/0"]
            ECSSG["SecurityGroup\necs_sg\nInbound: TCP 5000 from alb_sg\nInbound: TCP 6001 from alb_sg"]
        end

        subgraph ALBLayer["Load Balancer"]
            ALB["ApplicationLoadBalancer\ninternet_facing: True\nport: 80"]
            Listener["ApplicationListener\nRule 1: /api1* → TG1\nRule 2: /api2* → TG2\nDefault: 404"]
        end

        subgraph TGLayer["Target Groups"]
            TG1["ApplicationTargetGroup\ntg1\nport: 5000\ntarget_type: IP\nhealth: GET /api1"]
            TG2["ApplicationTargetGroup\ntg2\nport: 6001\ntarget_type: IP\nhealth: GET /api2"]
        end

        Role["IAM Role\nexec_role\nassumed_by: ecs-tasks\npolicy: ECSTaskExecutionRolePolicy"]

        subgraph API1Flow["API1 — Fargate Service 1"]
            Task1["FargateTaskDefinition\napi1_task\ncpu: 256  mem: 512MB"]
            Container1["ContainerDefinition\nimage: ECR api1:latest\nport: 5000\nlogs: CloudWatch"]
            Service1["FargateService\napi1_service\ndesired_count: 1\nassign_public_ip: True"]
        end

        subgraph API2Flow["API2 — Fargate Service 2"]
            Task2["FargateTaskDefinition\napi2_task\ncpu: 256  mem: 512MB"]
            Container2["ContainerDefinition\nimage: ECR api2:latest\nport: 6001\nlogs: CloudWatch"]
            Service2["FargateService\napi2_service\ndesired_count: 1\nassign_public_ip: True"]
        end

        Output["CfnOutput\nALBDnsName\nalb.load_balancer_dns_name"]

    end

    Stack -->|inherits| InfraStack
    Vpc --> ALBSG
    Vpc --> ECSSG
    Vpc --> ALB
    Vpc --> TG1
    Vpc --> TG2
    ALBSG --> ALB
    ALB --> Listener
    Listener --> TG1
    Listener --> TG2
    Role --> Task1
    Role --> Task2
    Task1 --> Container1
    Task1 --> Service1
    Task2 --> Container2
    Task2 --> Service2
    Service1 -->|attaches to| TG1
    Service2 -->|attaches to| TG2
    ALB --> Output
```
