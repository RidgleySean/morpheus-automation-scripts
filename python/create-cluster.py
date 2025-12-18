import requests
import socket
import time
import sys

# This scripts requires 2 custom options to be provided as inputs
# hvmCloud - The ID of the HVM cloud to create the cluster in
# clusterName - The name of the cluster to create
# These must be provided by the workflow for the cluster creation to succeed.
# Additionally, the Linux password for the instance must be provided as a script argument.
# Optionally, a clusterLayoutId custom option can be provided to specify the layout ID to use.
# If not provided, the default layout ID of 227 will be used.
# Optionally, an sshUserId custom option can be provided to specify the user ID whose SSH key will be used.
# If not provided, the default user ID of 1 will be used.
# Optionally, an sshHostName custom option can be provided to specify the hostname to use for SSH connections.
# If not provided, the hostname from the instance details will be used.
def getInputData():
    if 'hvmCloud' not in morpheus['customOptions']:
        print("Error: hvmCloud custom option is required.")
        sys.exit(1)
    if 'clusterName' not in morpheus['customOptions']:
        print("Error: clusterName custom option is required.")
        sys.exit(1)
    cloudId = morpheus['customOptions']['hvmCloud']
    clusterName = morpheus['customOptions']['clusterName']
    apiKey = morpheus['morpheus']['apiAccessToken']
    instanceId = morpheus['instance']['id']
    applianceUrl = morpheus['morpheus']['applianceUrl']
    if len(sys.argv) < 2:
        print("Error: Linux password argument is required.")
        sys.exit(1)
    linuxPassword = sys.argv[1]
    print("Creating an HVM cluster for instance ID: " + str(instanceId))
    print(f"cloudId: {cloudId}, clusterName: {clusterName}")
    clusterLayoutId = morpheus['customOptions'].get('clusterLayoutId', None)
    sshUserId = morpheus["customOptions"].get("sshUserId", 1)
    sshHostName = morpheus['customOptions'].get('sshHostName', None)
    return {
		'apiKey': apiKey,
		'cloudId': cloudId,
		'instanceId': instanceId,
		'clusterName': clusterName,
		'sshPassword': linuxPassword,
		'applianceUrl': applianceUrl,
        'clusterLayoutId': clusterLayoutId,
        'sshUserId': sshUserId,
        'sshHostName': sshHostName
	}

def getInstanceData(headers, inputData):
    print("Getting instance IP and group ID.")
    applianceUrl = inputData['applianceUrl']
    instancesUrl = f"{applianceUrl}/api/instances/{inputData['instanceId']}"
    response = requests.get(instancesUrl, headers=headers)
    print(f"response code: {response.status_code}")
    if (response.status_code != 200):
        print(f"An error occured: {response.text}")
        sys.exit(1)
    instanceData = response.json()
    instanceIp = instanceData["instance"]["connectionInfo"][0]["ip"]
    print(f"instance IP: {instanceIp}")
    groupId = instanceData["instance"]["group"]["id"]
    print(f"group ID: {groupId}")
    sshUsername = instanceData["instance"]["containerDetails"][0]["server"]["sshUsername"]
    if (inputData['sshHostName'] is None):
        hostName = instanceData["instance"]["containerDetails"][0]["externalHostname"]
    networkInterface = instanceData["instance"]["containerDetails"][0]["server"]["interfaces"][0]["name"]
    
    return {
        'instanceIp': instanceIp,
		'groupId': groupId,
        'sshUsername': sshUsername,
        'hostName': hostName,
        'networkInterface': networkInterface
	}

def getUserSshKeyId(headers, inputData):
    print("Getting user SSH key ID...")
    applianceUrl = inputData['applianceUrl']
    userUrl = f"{applianceUrl}/api/users/{inputData['sshUserId']}" # TODO get this from cloud-init
    #provisioningSettingsUrl = f"{applianceUrl}/api/provisioning-settings"
    response = requests.get(userUrl, headers=headers)
    print(f"response code: {response.status_code}")
    responseData = response.json()
    sshKeyId = responseData['user']['linuxKeyPairId'] # TODO this assumes the host VM is Linux.
    return sshKeyId

def postCluster(headers, inputData, instanceData, sshKeyId, clusterLayoutId):
    print("Creating HVM cluster...")
    applianceUrl = inputData['applianceUrl']
    clusterUrl = f"{applianceUrl}/api/clusters"
    data = {
		'cluster': {
			'type': "mvm-cluster",
			'group': {
				'id': int(instanceData['groupId'])
			},
			'name': inputData['clusterName'],
			'cloud': {
				'id': int(inputData['cloudId'])
			},
			'layout': {
				'id': int(clusterLayoutId)
			},
			'server': {
				"config": {
					"provisionKey": sshKeyId,
					"cpuArch": "x86_64",
					"cpuModel": "host-passthrough",
					"dynamicPlacementMode": "off",
					"powerPolicy": "balanced",
					"computeInterfaceName": "",
					"computeVlans": "",
					"overlayInterfaceName": "",
					"createUser": True
				},
				'name': inputData['clusterName'],
				'plan': {
					'id': 2,
					'code': "manual-default"
				},
				"securityGroups": [],
				'visibility': "private",
				'sshHosts': [
					{
						'ip': instanceData['instanceIp'],
						'name': instanceData['hostName']
					}
				],
				"sshPort": 22,
				'sshKeyPair': {
					'id': sshKeyId
				},
				'sshUsername': instanceData['sshUsername'],
				'sshPassword': inputData['sshPassword'],
				"network": {
					"name": instanceData['networkInterface']
				},
				"serverGroup": {
					"applianceUrlProxyBypass": "on"
				},
				"networkDomain": None,
				"hostname": instanceData['hostName']
			}
		}
	}
    response = requests.post(clusterUrl, json=data, headers=headers, verify=False)
    print(f"response code: {response.status_code}")
    if (response.status_code != 200):
    	print(f"An error occured: {response.text}")

def ensureSshAvailable(instanceIp):
    print("Checking SSH availability...")
    for _ in range(5):
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.connect((instanceIp, 22))
            test_socket.close()
            print(f"SSH is available on {instanceIp}")
            return True
        except socket.error:
            print(f"SSH not available on {instanceIp}, retrying...")
            time.sleep(30)
    return False

def getClusterLayoutId(headers, inputData):
    applianceUrl = inputData['applianceUrl']
    print("Getting cluster types...")
    clusterTypesUri = f"{applianceUrl}/api/library/cluster-types"
    clusterTypesResponse = requests.get(clusterTypesUri, headers=headers)
    print(f"response code: {clusterTypesResponse.status_code}")
    clusterTypes = clusterTypesResponse.json()
    for clusterType in clusterTypes['clusterTypes']:
        if clusterType['code'] == "mvm-cluster":
            groupTypeId = clusterType['id']
            break
    if groupTypeId is None:
        print("Could not determine hvm-cluster ID")
        sys.exit(1)
    print("Getting cluster layouts...")
    clusterLayoutsUri = f"{applianceUrl}/api/library/cluster-layouts?zoneId={int(inputData['cloudId'])}&groupTypeId={int(groupTypeId)}"
    clusterLayoutsResponse = requests.get(clusterLayoutsUri, headers=headers)
    print(f"response code: {clusterLayoutsResponse.status_code}")
    clusterLayouts = clusterLayoutsResponse.json()
    for layout in clusterLayouts['layouts']:
        if layout['code'] == "mvm-1.2-ubuntu-24.04-std-morpheus-amd64":
            return layout['id']
    print("Error: Could not determine cluster layout ID.")
    sys.exit(1)

inputData = getInputData()
headers = {
	'Accept': 'application/json',
    'Authorization': f"Bearer {inputData['apiKey']}",
    'Content-Type': 'application/json'
}
instanceData = getInstanceData(headers, inputData)
sshKeyId = getUserSshKeyId(headers, inputData)
if (inputData['clusterLayoutId'] is None):
    clusterLayoutId = getClusterLayoutId(headers, inputData)
else:
    clusterLayoutId = inputData['clusterLayoutId']
if ensureSshAvailable(instanceData['instanceIp']):
	postCluster(headers, inputData, instanceData, sshKeyId, clusterLayoutId)
else:
	print(f"SSH not available on {instanceData['instanceIp']} after multiple attempts. Exiting.")