// Storage-only addition. No web apps, DNS, certificates or shared plans touched.
targetScope = 'resourceGroup'

param location string = 'westus2'
param operatorObjectId string
param operatorIpv4 string
param deployObjectId string = '26ca884e-6914-4fad-9c4d-40b186830b88'

var blobContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'pilrelease9528'
  location: location
  tags: {
    application: 'image-library'
    purpose: 'release-lock-and-protected-rollback'
  }
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: [{ value: operatorIpv4, action: 'Allow' }]
    }
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for name in ['release-control', 'rollback-backups']: {
  parent: blobs
  name: name
  properties: { publicAccess: 'None' }
}]

resource deployAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (name, index) in ['release-control', 'rollback-backups']: {
  name: guid(storage.id, name, deployObjectId, blobContributor)
  scope: containers[index]
  properties: {
    principalId: deployObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributor
  }
}]

resource operatorAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (name, index) in ['release-control', 'rollback-backups']: {
  name: guid(storage.id, name, operatorObjectId, blobContributor)
  scope: containers[index]
  properties: {
    principalId: operatorObjectId
    principalType: 'User'
    roleDefinitionId: blobContributor
  }
}]

output accountId string = storage.id
output blobEndpoint string = storage.properties.primaryEndpoints.blob
