# Beats
  
Small program to grab fitbit data from its api and upload it to influxdb
  
## Build
```
docker build -t beats .
docker tag beats maxtara/beats:latest
docker push maxtara/beats
```
  
## Quick test
  
```
docker run -it --rm maxtara/beats python3 /beats.py
```
  
## Docker Compose
```
  beats:
    container_name: maxtara/beats
    image: beats
    restart: unless-stopped
    environment:
      DATE_OF_PURCHSE: '2022-01-01T00:00:00'
      OATH_FILE_LOCATION: "fitbit_oauth.json"
      INFLUXDBPASSWORD: 'admin'
      INFLUXDBUSERNAME: "admin"
      INFLUXDBIP: '192.168.1.1'
      INFLUXDB_DB: "fitbit"
```
