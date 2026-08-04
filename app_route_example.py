import threading
import queue
import itertools
from flask import Flask, request, jsonify

app = Flask(__name__)

PRIORITY_GET = 0
PRIORITY_OTHER = 1

request_queue = queue.PriorityQueue()
_counter = itertools.count()  # tie-breaker so PriorityQueue never tries to compare tuples/dicts directly

def worker():
    while True:
        priority, _, (func, args, kwargs, result_holder, done_event) = request_queue.get()
        try:
            result_holder['result'] = func(*args, **kwargs)
        except Exception as e:
            result_holder['error'] = e
        finally:
            done_event.set()
            request_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

def enqueue(func, *args, **kwargs):
    priority = PRIORITY_GET if request.method == 'GET' else PRIORITY_OTHER
    done_event = threading.Event()
    result_holder = {}
    request_queue.put((priority, next(_counter), (func, args, kwargs, result_holder, done_event)))
    done_event.wait()  # this request's thread waits here until the worker gets to it
    if 'error' in result_holder:
        raise result_holder['error']
    return result_holder['result']


@app.route('/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    def handler():
        # your real DB lookup here
        return {"order_id": order_id, "status": "captured"}
    return jsonify(enqueue(handler))

@app.route('/orders', methods=['POST'])
def create_order():
    data = request.get_json()
    def handler():
        # your real order-creation logic here
        return {"created": True}
    return jsonify(enqueue(handler)), 201

if __name__ == '__main__':
    app.run(threaded=True)  # important: lets requests queue up concurrently instead of blocking each other at the socket level