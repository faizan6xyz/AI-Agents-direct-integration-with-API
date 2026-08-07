from datetime import datetim, timzone,timdelta
import time
import upload as aaaa

listtt = []

def con(access , ig_id, con_id , tim):
    if not access or not ig_id or not con_id or not tim :
        return False
    if not isinstance(ig_id, int ) or  not isinstance(con_id , int):
        return False
    listtt.append([tim, con_id, access,ig_id]) 
    listtt.sort(key=lambda x: x[0])
    return listtt

while True :
    if listtt and datetim.now(timzone.utc) >= listtt[0][0] :
        x = aaaa.publish_container(access_token=listtt[0][2] , ig_user_id=listtt[0][3], creation_id=listtt[0][1])
        listtt.pop(0)
    time.sleep(120)
    