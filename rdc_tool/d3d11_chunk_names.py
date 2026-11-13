# The MIT License (MIT)
#
# Copyright (c) 2015-2026 Baldur Karlsson
# Copyright (c) 2014 Crytek
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

"""D3D11 chunk names from RenderDoc v1.47 d3d11_common.h (MIT license).
https://github.com/baldurk/renderdoc/blob/v1.47/renderdoc/driver/d3d11/d3d11_common.h
"""
NAMES = ('DeviceInitialisation', 'SetResourceName', 'CreateSwapBuffer', 'CreateTexture1D', 'CreateTexture2D', 'CreateTexture3D', 'CreateBuffer', 'CreateVertexShader', 'CreateHullShader', 'CreateDomainShader', 'CreateGeometryShader', 'CreateGeometryShaderWithStreamOutput', 'CreatePixelShader', 'CreateComputeShader', 'GetClassInstance', 'CreateClassInstance', 'CreateClassLinkage', 'CreateShaderResourceView', 'CreateRenderTargetView', 'CreateDepthStencilView', 'CreateUnorderedAccessView', 'CreateInputLayout', 'CreateBlendState', 'CreateDepthStencilState', 'CreateRasterizerState', 'CreateSamplerState', 'CreateQuery', 'CreatePredicate', 'CreateCounter', 'CreateDeferredContext', 'SetExceptionMode', 'OpenSharedResource', 'IASetInputLayout', 'IASetVertexBuffers', 'IASetIndexBuffer', 'IASetPrimitiveTopology', 'VSSetConstantBuffers', 'VSSetShaderResources', 'VSSetSamplers', 'VSSetShader', 'HSSetConstantBuffers', 'HSSetShaderResources', 'HSSetSamplers', 'HSSetShader', 'DSSetConstantBuffers', 'DSSetShaderResources', 'DSSetSamplers', 'DSSetShader', 'GSSetConstantBuffers', 'GSSetShaderResources', 'GSSetSamplers', 'GSSetShader', 'SOSetTargets', 'PSSetConstantBuffers', 'PSSetShaderResources', 'PSSetSamplers', 'PSSetShader', 'CSSetConstantBuffers', 'CSSetShaderResources', 'CSSetUnorderedAccessViews', 'CSSetSamplers', 'CSSetShader', 'RSSetViewports', 'RSSetScissorRects', 'RSSetState', 'OMSetRenderTargets', 'OMSetRenderTargetsAndUnorderedAccessViews', 'OMSetBlendState', 'OMSetDepthStencilState', 'DrawIndexedInstanced', 'DrawInstanced', 'DrawIndexed', 'Draw', 'DrawAuto', 'DrawIndexedInstancedIndirect', 'DrawInstancedIndirect', 'Map', 'Unmap', 'CopySubresourceRegion', 'CopyResource', 'UpdateSubresource', 'CopyStructureCount', 'ResolveSubresource', 'GenerateMips', 'ClearDepthStencilView', 'ClearRenderTargetView', 'ClearUnorderedAccessViewUint', 'ClearUnorderedAccessViewFloat', 'ClearState', 'ExecuteCommandList', 'Dispatch', 'DispatchIndirect', 'FinishCommandList', 'Flush', 'SetPredication', 'SetResourceMinLOD', 'Begin', 'End', 'CreateRasterizerState1', 'CreateBlendState1', 'CopySubresourceRegion1', 'UpdateSubresource1', 'ClearView', 'VSSetConstantBuffers1', 'HSSetConstantBuffers1', 'DSSetConstantBuffers1', 'GSSetConstantBuffers1', 'PSSetConstantBuffers1', 'CSSetConstantBuffers1', 'PushMarker', 'SetMarker', 'PopMarker', 'SetShaderDebugPath', 'DiscardResource', 'DiscardView', 'DiscardView1', 'CreateRasterizerState2', 'CreateQuery1', 'CreateTexture2D1', 'CreateTexture3D1', 'CreateShaderResourceView1', 'CreateRenderTargetView1', 'CreateUnorderedAccessView1', 'SwapchainPresent', 'PostExecuteCommandList', 'PostFinishCommandListSet', 'SwapDeviceContextState', 'ExternalDXGIResource', 'OpenSharedResource1', 'OpenSharedResourceByName', 'SetShaderExtUAV', 'SetCommandAnnotation', 'Max')
