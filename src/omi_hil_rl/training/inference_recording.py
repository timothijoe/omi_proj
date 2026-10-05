"""Bounded nonblocking recording of exact pre-normalization network windows."""
import json
import os
from pathlib import Path
import queue
import threading
import numpy as np


class InferenceRecorder:
    def __init__(self, directory, max_bytes=10*1024**3, queue_size=16):
        if max_bytes <= 0 or queue_size < 1:raise ValueError('invalid recording limits')
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=False)
        self.queue=queue.Queue(maxsize=queue_size)
        self.max_bytes=max_bytes;self.bytes=0;self.saved=0;self.dropped=0
        self.errors=[];self.closed=False
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    def submit(self, window, action, status):
        if self.closed:raise RuntimeError('recorder already closed')
        if self.errors or self.bytes>=self.max_bytes:
            self.dropped+=1;return 'disabled_after_error_or_capacity'
        if self.queue.full():
            self.dropped+=1;return 'queue_full'
        data,mask=window
        arrays={k:np.array(v,copy=True) for k,v in data.items()}
        arrays.update(history_mask=np.array(mask,copy=True),action=np.array(action,copy=True),
            metadata=np.asarray(json.dumps(status,allow_nan=False)))
        name=f"{status['reference_ns']}_{status.get('epoch',0)}.npz"
        try:self.queue.put_nowait((name,arrays))
        except queue.Full:
            self.dropped+=1;return 'queue_full'
        return name

    def _write(self, name, arrays):
        path=self.directory/name;temporary=path.with_suffix('.npz.partial')
        try:
            with temporary.open('xb') as out:
                np.savez_compressed(out,**arrays);out.flush();os.fsync(out.fileno())
            size=temporary.stat().st_size
            if self.bytes+size>self.max_bytes:
                temporary.unlink();self.dropped+=1;self.errors.append('recording_capacity_reached');return
            temporary.replace(path);self.bytes+=size;self.saved+=1
        except Exception:
            # Keep an incomplete file for diagnosis; never rename it to a complete sample.
            raise

    def _run(self):
        while True:
            item=self.queue.get()
            try:
                if item is None:return
                if self.errors:self.dropped+=1;continue
                self._write(*item)
            except Exception as exc:
                self.errors.append(repr(exc));self.dropped+=1
            finally:self.queue.task_done()

    def close(self):
        self.closed=True
        self.queue.put(None);self.thread.join()
        report=dict(saved=self.saved,dropped=self.dropped,bytes=self.bytes,errors=self.errors,
                    flushed=True,complete=self.dropped==0 and not self.errors,
                    data='exact pre-normalization windows; action is unscaled model output in m/rad',
                    join_key='reference_ns; match selected_policy_reference_ns in selected_actions.jsonl')
        path=self.directory/'summary.json'
        with path.open('x') as out:
            json.dump(report,out,indent=2);out.flush();os.fsync(out.fileno())
        return report
