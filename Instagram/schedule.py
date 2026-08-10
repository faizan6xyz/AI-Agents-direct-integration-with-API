from datetime import datetime, timezone,timedelta
import time
import upload as aaaa

listtt = []

def con(access , ig_id, con_id , timee):
    if not access or not ig_id or not con_id or not timee :
        return False
    if not isinstance(ig_id, int ) or  not isinstance(con_id , int):
        return False
    listtt.append([timee, con_id, access,ig_id]) 
    listtt.sort(key=lambda x: x[0])
    return listtt

while True :
    if listtt and datetime.now(timezone.utc) >= listtt[0][0] :
        x = aaaa.publish_container(access_token=listtt[0][2] , ig_user_id=listtt[0][3], creation_id=listtt[0][1])
        listtt.pop(0)
    time.sleep(120)

# set the publish date to the max 36 hours because by default the tokens refresh after the 2 days are left 