from __future__ import print_function
import torch
import torch.nn as nn
import torch.utils.data
from torch.autograd import Variable
import torch.nn.functional as F
import math
from models.submodule import *
from inverse_warp import inverse_warp

import pdb

def convtext(in_planes, out_planes, kernel_size = 3, stride = 1, dilation = 1):

    return nn.Sequential(
        nn.Conv2d(in_planes, out_planes, kernel_size = kernel_size, stride = stride, dilation = dilation, padding = ((kernel_size - 1) * dilation) // 2, bias=False),
        nn.LeakyReLU(0.1,inplace=True)
    )

class PSNet(nn.Module):
    def __init__(self, nlabel, mindepth):
        super(PSNet, self).__init__()
        self.nlabel = nlabel
        self.mindepth = mindepth

        self.feature_extraction = feature_extraction()

        self.convs = nn.Sequential(
            convtext(33, 128, 3, 1, 1),
            convtext(128, 128, 3, 1, 2),
            convtext(128, 128, 3, 1, 4),
            convtext(128, 96, 3, 1, 8),
            convtext(96, 64, 3, 1, 16),
            convtext(64, 32, 3, 1, 1),
            convtext(32, 1, 3, 1, 1)
        )

        self.dres0 = nn.Sequential(convbn_3d(64, 32, 3, 1, 1),
                                     nn.ReLU(inplace=True),
                                     convbn_3d(32, 32, 3, 1, 1),
                                     nn.ReLU(inplace=True))

        self.dres1 = nn.Sequential(convbn_3d(32, 32, 3, 1, 1),
                                   nn.ReLU(inplace=True),
                                   convbn_3d(32, 32, 3, 1, 1)) 

        self.dres2 = nn.Sequential(convbn_3d(32, 32, 3, 1, 1),
                                   nn.ReLU(inplace=True),
                                   convbn_3d(32, 32, 3, 1, 1))
 
        self.dres3 = nn.Sequential(convbn_3d(32, 32, 3, 1, 1),
                                   nn.ReLU(inplace=True),
                                   convbn_3d(32, 32, 3, 1, 1)) 

        self.dres4 = nn.Sequential(convbn_3d(32, 32, 3, 1, 1),
                                   nn.ReLU(inplace=True),
                                   convbn_3d(32, 32, 3, 1, 1)) 
 
        self.classify = nn.Sequential(convbn_3d(32, 32, 3, 1, 1),
                                      nn.ReLU(inplace=True),
                                      nn.Conv3d(32, 1, kernel_size=3, padding=1, stride=1,bias=False))

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.Conv3d):
                n = m.kernel_size[0] * m.kernel_size[1]*m.kernel_size[2] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.BatchNorm3d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()

    def init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d) or isinstance(m, nn.ConvTranspose2d):
                nn.init.xavier_uniform(m.weight.data)
                if m.bias is not None:
                    m.bias.data.zero_()


    def forward(self, ref, targets, pose, intrinsics, intrinsics_inv):

        intrinsics4 = intrinsics.clone()
        intrinsics_inv4 = intrinsics_inv.clone()
        intrinsics4[:,:2,:] = intrinsics4[:,:2,:] / 4
        intrinsics_inv4[:,:2,:2] = intrinsics_inv4[:,:2,:2] * 4

        """
        1. Reference image Feature Extraction
        """
        refimg_fea     = self.feature_extraction(ref)


        #inst_seg_fea =

        """
        2. Target image Featrue Extraction
           & Feature Volume Generation
           & Cost Volume Geneartion
        """
        disp2depth = Variable(torch.ones(refimg_fea.size(0), refimg_fea.size(2), refimg_fea.size(3))).cuda() * self.mindepth * self.nlabel
        for j, target in enumerate(targets):
            cost = Variable(torch.FloatTensor(refimg_fea.size()[0], refimg_fea.size()[1]*2, self.nlabel,  refimg_fea.size()[2],  refimg_fea.size()[3]).zero_()).cuda()
            # Target Image Feature Extraction
            targetimg_fea  = self.feature_extraction(target)
            for i in range(self.nlabel):
                depth = torch.div(disp2depth, i+1e-16)
                targetimg_fea_t = inverse_warp(targetimg_fea, depth, pose[:,j], intrinsics4, intrinsics_inv4)
                # Feature Volume Generation
                cost[:, :refimg_fea.size()[1], i, :,:] = refimg_fea
                cost[:, refimg_fea.size()[1]:, i, :,:] = targetimg_fea_t

            # Cost Volume Generation
            cost = cost.contiguous()
            cost0 = self.dres0(cost)
            cost0 = self.dres1(cost0) + cost0
            cost0 = self.dres2(cost0) + cost0 
            cost0 = self.dres3(cost0) + cost0 
            cost0 = self.dres4(cost0) + cost0
            cost0 = self.classify(cost0)

            if j == 0:
                costs = cost0
            else:
                costs = costs + cost0

        costs = costs/len(targets)

        pdb.set_trace()

        """
        3. Cost Aggregation
        """
        costss = Variable(torch.FloatTensor(refimg_fea.size()[0], 1, self.nlabel,  refimg_fea.size()[2],  refimg_fea.size()[3]).zero_()).cuda()
        for i in range(self.nlabel):
            costt = costs[:, :, i, :, :]
            costss[:, :, i, :, :] = self.convs(torch.cat([refimg_fea, costt],1)) + costt

        """
        4. Depth Regression
        """
        costs = F.upsample(costs, [self.nlabel,ref.size()[2],ref.size()[3]], mode='trilinear')
        costs = torch.squeeze(costs,1)
        pred0 = F.softmax(costs,dim=1)
        pred0 = disparityregression(self.nlabel)(pred0)
        depth0 = self.mindepth*self.nlabel/(pred0.unsqueeze(1)+1e-16)

        costss = F.upsample(costss, [self.nlabel,ref.size()[2],ref.size()[3]], mode='trilinear')
        costss = torch.squeeze(costss,1)
        pred = F.softmax(costss,dim=1)
        pred = disparityregression(self.nlabel)(pred)
        depth = self.mindepth*self.nlabel/(pred.unsqueeze(1)+1e-16)

        if self.training:
            return depth0, depth
        else:
            return depth
