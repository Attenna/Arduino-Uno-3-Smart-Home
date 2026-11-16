"""Fixed-shape Ascend OM execution using the board's pyACL runtime."""
import threading
import numpy as np


def check(code, operation):
    if code != 0:
        raise RuntimeError(f'Ascend {operation} failed ({code})')


class AscendRunner:
    def __init__(self, model_path):
        import acl
        self.acl = acl
        self.lock = threading.Lock()
        self.allocations = []
        self.buffers = []
        self.datasets = []
        self.model = self.desc = self.context = None
        check(acl.init(), 'init')
        try:
            check(acl.rt.set_device(0), 'set_device')
            self.context, code = acl.rt.create_context(0)
            check(code, 'create_context')
            self.model, code = acl.mdl.load_from_file(str(model_path))
            check(code, 'load_model')
            self.desc = acl.mdl.create_desc()
            check(acl.mdl.get_desc(self.desc, self.model), 'get_desc')
            if acl.mdl.get_num_inputs(self.desc) != 1 or acl.mdl.get_num_outputs(self.desc) != 1:
                raise ValueError('Expected one input and one output')
            dims, code = acl.mdl.get_input_dims(self.desc, 0)
            check(code, 'input_dimensions')
            self.input_shape = tuple(dims['dims'])
            dims, code = acl.mdl.get_output_dims(self.desc, 0)
            check(code, 'output_dimensions')
            self.output_shape = tuple(dims['dims'])
            if acl.mdl.get_input_data_type(self.desc, 0) != 0 or acl.mdl.get_output_data_type(self.desc, 0) != 0:
                raise ValueError('Expected float32 input and output')
            for size in [acl.mdl.get_input_size_by_index(self.desc, 0), acl.mdl.get_output_size_by_index(self.desc, 0)]:
                dataset = acl.mdl.create_dataset()
                self.datasets.append(dataset)
                pointer, code = acl.rt.malloc(size, 0)
                check(code, 'allocate')
                self.allocations.append((pointer, size))
                buffer = acl.create_data_buffer(pointer, size)
                self.buffers.append(buffer)
                _, code = acl.mdl.add_dataset_buffer(dataset, buffer)
                check(code, 'add_buffer')
        except Exception:
            self.close()
            raise

    def infer(self, tensor):
        tensor = np.ascontiguousarray(tensor, dtype=np.float32)
        if tensor.shape != self.input_shape or tensor.nbytes != self.allocations[0][1]:
            raise ValueError('Unexpected input shape or byte size')
        output = np.empty(self.output_shape, dtype=np.float32)
        if output.nbytes != self.allocations[1][1]:
            raise ValueError('Unexpected output byte size')
        acl = self.acl
        with self.lock:
            check(acl.rt.set_context(self.context), 'set_context')
            pointer, size = self.allocations[0]
            check(acl.rt.memcpy(pointer, size, tensor.ctypes.data, tensor.nbytes, 1), 'copy_input')
            check(acl.mdl.execute(self.model, *self.datasets), 'execute')
            pointer, size = self.allocations[1]
            check(acl.rt.memcpy(output.ctypes.data, output.nbytes, pointer, size, 2), 'copy_output')
        return output

    def close(self):
        acl = self.acl
        for buffer in self.buffers:
            acl.destroy_data_buffer(buffer)
        for pointer, _ in self.allocations:
            acl.rt.free(pointer)
        for dataset in self.datasets:
            acl.mdl.destroy_dataset(dataset)
        if self.desc is not None:
            acl.mdl.destroy_desc(self.desc)
        if self.model is not None:
            acl.mdl.unload(self.model)
        if self.context is not None:
            acl.rt.destroy_context(self.context)
        acl.rt.reset_device(0)
        acl.finalize()
