targetScope = 'resourceGroup'

@description('Only the operator public IPv4/CIDR; pilot denies other inbound traffic.')
param operatorCidr string
param location string = 'westus2'
var tags = { application: 'proxima-image-library', purpose: 'container-pilot' }
var readerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b93aa761-3e63-49ed-ac28-beffa264f7ac')
var writerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a1e307c-b015-4ebd-883e-5b7698a07328')
var controlReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
var websiteRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'de139f84-1756-47ae-9be6-808fbbe84772')
var readCondition = '''
((!(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/read'}) AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/read'})) OR (@Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEquals 'image-library'))
'''
var writeCondition = '''
((!(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/read'}) AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/read'}) AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/write'}) AND !(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/write'})) OR (@Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEquals 'image-library' OR @Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEquals 'image-library-buildcache'))
'''
// Settings live on the separate /config/appsettings surface. Configure through
// configure_container_pilot.py, which merges existing values and never logs them.
// Omitting them here prevents a later infra reconciliation replacing secrets.
var siteConfig = {
  linuxFxVersion: 'sitecontainers'
  alwaysOn: true
  ftpsState: 'Disabled'
  minTlsVersion: '1.2'
  scmMinTlsVersion: '1.2'
  http20Enabled: true
  healthCheckPath: '/readyz'
  ipSecurityRestrictions: [{ name: 'pilot-operator', ipAddress: operatorCidr, action: 'Allow', priority: 100 }]
  ipSecurityRestrictionsDefaultAction: 'Deny'
  scmIpSecurityRestrictionsUseMain: true
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: 'proximaimagelibrary'
  location: location
  tags: tags
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    roleAssignmentMode: 'AbacRepositoryPermissions'
    publicNetworkAccess: 'Enabled'
    policies: {
      retentionPolicy: { status: 'disabled' }
      azureADAuthenticationAsArmPolicy: { status: 'enabled' }
    }
  }
}
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'asp-image-library-p2v3'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'P2v3', tier: 'PremiumV3', capacity: 1 }
  properties: { reserved: true }
}
resource app 'Microsoft.Web/sites@2024-04-01' = {
  name: 'pp-image-library'
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientCertEnabled: false
    publicNetworkAccess: 'Enabled'
    siteConfig: siteConfig
  }
}
resource staging 'Microsoft.Web/sites/slots@2024-04-01' = {
  parent: app
  name: 'staging'
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientCertEnabled: false
    publicNetworkAccess: 'Enabled'
    siteConfig: siteConfig
  }
}
resource sticky 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: app
  name: 'slotConfigNames'
  properties: {
    appSettingNames: [
      'APP_READ_ONLY'
      'INGEST_POLLER_ENABLED'
      'INGEST_OWNER_HOSTNAME'
      'APP_BASE_URL'
      'MSAL_REDIRECT_URI'
      'CORS_ORIGINS'
      'FLASK_SECRET_KEY'
      'OTEL_SERVICE_NAME'
      'OTEL_RESOURCE_ATTRIBUTES'
    ]
  }
}
resource buildIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-image-library-build'
  location: location
  tags: tags
}
resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-image-library-deploy'
  location: location
  tags: tags
}
resource buildOidc 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: buildIdentity
  name: 'github-pilot-build'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:Proxima-Partners/proxima-image-library:environment:image-library-build'
    audiences: ['api://AzureADTokenExchange']
  }
}
resource deployOidc 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: deployIdentity
  name: 'github-pilot-deploy'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:Proxima-Partners/proxima-image-library:environment:image-library-pilot'
    audiences: ['api://AzureADTokenExchange']
  }
}
resource appPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, app.id, readerRole)
  scope: registry
  properties: {
    roleDefinitionId: readerRole
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: readCondition
  }
}
resource slotPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, staging.id, readerRole)
  scope: registry
  properties: {
    roleDefinitionId: readerRole
    principalId: staging.identity.principalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: readCondition
  }
}
resource buildPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, buildIdentity.id, writerRole)
  scope: registry
  properties: {
    roleDefinitionId: writerRole
    principalId: buildIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: writeCondition
  }
}
resource buildControlRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, buildIdentity.id, controlReaderRole)
  scope: registry
  properties: {
    roleDefinitionId: controlReaderRole
    principalId: buildIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource deployApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(app.id, deployIdentity.id, websiteRole)
  scope: app
  properties: {
    roleDefinitionId: websiteRole
    principalId: deployIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
output registryHost string = registry.properties.loginServer
output appHost string = app.properties.defaultHostName
output stagingHost string = staging.properties.defaultHostName
output buildClientId string = buildIdentity.properties.clientId
output deployClientId string = deployIdentity.properties.clientId
output appId string = app.id
output planId string = plan.id
