import {loadSource} from './helpers/source-module.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const {observationChannel}=await loadSource(new URL('../web/assets/operator/observations.js',import.meta.url));
const channel=(name,value,unit)=>observationChannel({
 contract_id:'rider.telemetry',contract_version:1,
 sensor_quality:{sensors:{[name]:{value,unit,observed_at:100,ready:true}}}
},name,{now:101});
test('acceleration has explicit units and fresh value',()=>{
 assert.equal(channel('accel_z',9.7,'m/s^2').value,9.7);
 assert.equal(channel('accel_z',9.7,'sdk_raw').ready,false);
});
test('work status zero is a valid measurement; other codes are rejected',()=>{
 assert.equal(channel('work_status',0,'code').value,0);
 assert.equal(channel('work_status',1,'code').value,1);
 assert.equal(channel('work_status',2,'code').ready,false);
});
