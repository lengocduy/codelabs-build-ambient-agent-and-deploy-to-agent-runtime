terraform {
  backend "gcs" {
    bucket = "gen-lang-client-0513235234-terraform-state"
    prefix = "codelabs-build-ambient-agent-and-deploy-to-agent-runtime/dev"
  }
}
