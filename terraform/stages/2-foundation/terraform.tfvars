project_id              = "your-project-id"
project_number          = "your-project-number"
region                  = "us-central1"
storage_multiregion     = "US"
vpc_network             = "default-vpc"
vpc_subnetwork          = "default-vpc-subnet"
ip_cidr_range           = "10.0.0.0/16"
master_ipv4_cidr_block  = "172.16.0.0/28"
existing_firestore_name = "projects/your-project-id/databases/(default)"
secondary_ranges_pods = {
  range_name    = "secondary-pod-range-01"
  ip_cidr_range = "10.1.0.0/16"
}
secondary_ranges_services = {
  range_name    = "secondary-service-range-01"
  ip_cidr_range = "10.2.0.0/16"
}
