flowchart LR

User[User Browser]

DNS[Route 53<br>DNS Resolution]

subgraph VPC
    IGW[Internet Gateway]

    subgraph Public Subnet
        ALB[Application Load Balancer<br>Listener :80]
    end

    subgraph Private Subnet
        subgraph ECS Task
            ENI[Task ENI<br>Private IP]
            API1[Container API1<br>Port 5000]
            API2[Container API2<br>Port 6000]
        end
    end
end

TG1[Target Group API1<br>IP:5000]
TG2[Target Group API2<br>IP:6000]

User -->|api.myapp.com/api1| DNS
DNS --> ALB
ALB -->|Path /api1| TG1
ALB -->|Path /api2| TG2
TG1 --> ENI
TG2 --> ENI
ENI --> API1
ENI --> API2
